"""The absent-symbol rejection and the ``contract_violation`` outcome.

Feature 12 of app_spec.xml: "System rejects a signal return value whose index
contains a symbol absent from the window universe, which emits a
contract_violation outcome."

Feature 11's suite (``test_signal.py``) stops at "name the failure" — it pins
what a *conforming* return is and deliberately leaves the consequence to this
feature.  So this suite is written against the three things feature 12 adds,
each pinned in its own section:

* **the index is readable.**  "Index" needs a definition, because Polars has
  none: a series has no ``.index``, and the conforming return of feature 11 is
  a *bare* series carrying no labels at all.  A return that claims labels
  anyway does so through one of the carriers Polars does offer — a DataFrame's
  ``symbol`` column, a struct field, a mapping's keys, a series named after a
  symbol — and ``return_index`` reads all four.  The suite asserts each, and
  asserts the case that matters most: a *conforming* bare series must claim
  **nothing**, since a checker that read a series' name as an index would
  reject correct signals.
* **the rejection.**  ``absent_symbol_problems`` names the symbol and its
  position for every claim the universe does not list, and stays silent when
  the claim is true.
* **the outcome.**  ``check_signal_return`` emits ``contract_violation`` or
  ``ok`` as a *value* — never a raise — composing feature 11's value checks
  with this feature's label checks rather than replacing them.  Two properties
  the suite spends effort on: the outcome is faithful to *both* halves (a
  mislabeled ``DataFrame`` reports an index violation *and* a shape
  violation), and it is pure and deterministic over (return, universe), which
  is what lets a replay reach the same verdict.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# polars is a declared dependency of the contract member, so under the
# canonical invocation (`uv run --all-packages pytest`, which installs every
# member's dependencies) it is always present.  It is imported at module scope
# — not lazily — because this module is meaningless without it, mirroring
# `test_signal.py` and `test_payload.py` in this directory; the tests
# themselves exercise the module's *lazy* import, in a subprocess, where the
# difference is observable.
import polars as pl
import pytest

from contract import (
    CONTRACT_VIOLATION,
    INDEX_LABEL_FIELD,
    OUTCOME_OK,
    QUOTE_ASSETS,
    SignalReturnOutcome,
    absent_symbol_problems,
    check_signal_return,
    is_symbol_label,
    return_index,
    universe_symbols,
)

UNIVERSE = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
REPO_ROOT = Path(__file__).resolve().parents[2]


class Window:
    """A stand-in for :class:`contract.MarketWindow` in these tests.

    Feature 12 reads a window's universe and nothing else, so the suite drives
    it with the smallest object that answers the one question asked.  That is
    not just brevity: ``universe_symbols`` ducks the ``universe`` attribute
    rather than ``isinstance``-ing the window class on purpose (the factory
    imports a scanned package under a synthetic name, across which
    ``isinstance`` silently fails), and a stand-in that is *not* a
    ``MarketWindow`` is what proves the seam is really duck-typed.
    """

    def __init__(self, universe) -> None:
        self.universe = universe


def labelled_frame(symbols, scores) -> pl.DataFrame:
    """The most common mislabeling carrier: a frame with a ``symbol`` column."""
    return pl.DataFrame({INDEX_LABEL_FIELD: list(symbols), "score": list(scores)})


def labelled_struct(symbols, scores) -> pl.Series:
    """The second carrier: a struct series with a ``symbol`` field."""
    return pl.Series(
        "return",
        [
            {INDEX_LABEL_FIELD: symbol, "score": score}
            for symbol, score in zip(symbols, scores)
        ],
    )


# --------------------------------------------------------------------------
# Reading the index — what does a return claim?
# --------------------------------------------------------------------------


def test_a_bare_series_claims_no_index():
    # The conforming return of feature 11 is a bare, positionally-paired
    # series.  If this returned anything, every correct signal would be a
    # false positive — the one failure mode worse than missing a real one.
    assert return_index(pl.Series("score", [0.1, 0.2, 0.3])) == ()


def test_an_unnamed_series_claims_no_index():
    # polars' "unnamed" is the empty string, which is not a claim.
    assert return_index(pl.Series([0.1, 0.2, 0.3])) == ()


def test_a_series_named_after_a_symbol_claims_that_symbol():
    # The docstring every signal is written against says "index=symbol"; a
    # single-symbol return that names itself is the smallest way to say it.
    assert return_index(pl.Series("DOGEUSDT", [0.3])) == ("DOGEUSDT",)


def test_a_frame_with_a_symbol_column_claims_the_column():
    assert return_index(labelled_frame(["BTCUSDT", "DOGEUSDT"], [1.0, 2.0])) == (
        "BTCUSDT",
        "DOGEUSDT",
    )


def test_a_frame_without_a_symbol_column_claims_nothing():
    # No column named `symbol` means no label was declared; the values are
    # positional, exactly as a bare series' are.
    assert return_index(pl.DataFrame({"score": [1.0, 2.0]})) == ()


def test_a_struct_series_claims_its_symbol_field():
    assert return_index(labelled_struct(["BTCUSDT", "DOGEUSDT"], [1.0, 2.0])) == (
        "BTCUSDT",
        "DOGEUSDT",
    )


def test_a_struct_field_wins_over_the_series_name():
    # An explicit field is a declaration; the series' name is a name.  When
    # both are present the declaration is the claim.
    struct_named_after_a_symbol = labelled_struct(["BTCUSDT"], [1.0]).rename(
        "DOGEUSDT"
    )
    assert return_index(struct_named_after_a_symbol) == ("BTCUSDT",)


def test_a_nested_symbol_field_is_not_read():
    # Only the top-level field is a declaration.  Searching deeper would make
    # "which field is the index" a search this module performs rather than a
    # shape the return declares.
    nested = pl.Series("n", [{"outer": {INDEX_LABEL_FIELD: "DOGEUSDT"}}])
    assert return_index(nested) == ()


def test_a_mapping_claims_its_keys():
    assert return_index({"BTCUSDT": 0.5, "DOGEUSDT": 0.2}) == (
        "BTCUSDT",
        "DOGEUSDT",
    )


def test_labels_are_read_in_return_order():
    # Order is what makes a problem's `position` actionable: it points at the
    # row that produced the mislabeling.
    assert return_index(labelled_frame(["C", "A", "B"], [1.0, 2.0, 3.0])) == (
        "C",
        "A",
        "B",
    )


def test_a_null_label_is_carried_through_unvalidated():
    # Reading a carrier and judging its labels are separate jobs — this is the
    # reading half, so it hands back what was there.
    assert return_index(labelled_frame(["BTCUSDT", None], [1.0, 2.0])) == (
        "BTCUSDT",
        None,
    )


def test_an_unlabelled_object_claims_nothing():
    for unlabelled in ([0.1, 0.2], "not a return", 42, None):
        assert return_index(unlabelled) == ()


# --------------------------------------------------------------------------
# The ticker-shape rule — a name is not an index
# --------------------------------------------------------------------------


def test_symbol_shaped_labels_are_recognised():
    for label in ("BTCUSDT", "ETHBTC", "SOLUSDC", "1INCHUSDT", "PEPEUSD"):
        assert is_symbol_label(label), label


def test_series_names_are_not_symbol_shaped():
    # The distinction that keeps this feature from rejecting correct signals:
    # a series called "score" is the conforming return, not a symbol claim.
    for label in ("score", "VOL", "S1", "momentum", "signal_1", "rank", "z"):
        assert not is_symbol_label(label), label


def test_lower_case_is_not_read_as_a_symbol_claim():
    # The universe's canonical casing is authoritative (feature 46); a
    # lower-cased ticker is not silently accepted as the symbol it resembles.
    assert not is_symbol_label("btcusdt")
    assert check_signal_return(pl.Series("btcusdt", [0.3]), ("BTCUSDT",)).ok


def test_an_unknown_quote_asset_is_not_read_as_a_symbol_claim():
    # A base asset with no recognised quote: defaults to "a name", because a
    # false rejection of a correct signal is the worse error.
    assert not is_symbol_label("BTCXYZ")


def test_non_strings_are_never_symbol_labels():
    for value in (None, 42, 3.5, b"BTCUSDT", ("BTCUSDT",)):
        assert not is_symbol_label(value)


def test_a_trailing_newline_does_not_pass_as_a_symbol():
    # The pattern is anchored with \A/\Z, so a label that differs from the
    # symbol by an invisible character is not read as the symbol.
    assert not is_symbol_label("BTCUSDT\n")


def test_quote_assets_are_a_declared_inspectable_list():
    assert "USDT" in QUOTE_ASSETS and "BTC" in QUOTE_ASSETS
    assert all(isinstance(q, str) and q.isupper() for q in QUOTE_ASSETS)


# --------------------------------------------------------------------------
# The rejection — a claimed symbol absent from the window universe
# --------------------------------------------------------------------------


def test_absent_symbol_is_rejected_and_carries_the_symbol():
    problems = absent_symbol_problems(pl.Series("DOGEUSDT", [0.3]), UNIVERSE)
    assert len(problems) == 1
    assert problems[0].kind == "absent_symbol"
    assert problems[0].symbol == "DOGEUSDT"
    assert "DOGEUSDT" in problems[0].message
    assert "absent" in problems[0].message


def test_a_present_symbol_is_not_rejected():
    assert absent_symbol_problems(
        labelled_frame(UNIVERSE, [0.1, 0.2, 0.3]), UNIVERSE
    ) == []


def test_only_the_absent_symbols_are_reported():
    # A correctly-labeled frame with one stranger: the known labels are true
    # claims and are not complained about.
    problems = absent_symbol_problems(
        labelled_frame(["BTCUSDT", "DOGEUSDT", "ETHUSDT"], [1.0, 2.0, 3.0]),
        UNIVERSE,
    )
    assert [p.symbol for p in problems] == ["DOGEUSDT"]
    assert [p.kind for p in problems] == ["absent_symbol"]


def test_every_absent_symbol_is_reported_per_position():
    problems = absent_symbol_problems(
        labelled_frame(["DOGEUSDT", "BTCUSDT", "SHIBUSDT"], [1.0, 2.0, 3.0]),
        UNIVERSE,
    )
    assert [p.symbol for p in problems] == ["DOGEUSDT", "SHIBUSDT"]
    # Each names its position, so an author can find the row that produced it.
    assert "position 0" in problems[0].message
    assert "position 2" in problems[1].message


def test_a_repeated_absent_symbol_is_reported_once_per_occurrence():
    # The list is in return order and one entry per offending label, so the
    # count still tells an author how many rows are misattributed.
    problems = absent_symbol_problems(
        labelled_frame(["DOGEUSDT", "DOGEUSDT"], [1.0, 2.0]), UNIVERSE
    )
    assert [p.symbol for p in problems] == ["DOGEUSDT", "DOGEUSDT"]


def test_a_null_label_is_malformed_not_absent():
    # A null cannot name any symbol, so it is reported as the malformed claim
    # it is, rather than sending an author hunting for a spelling mistake.
    problems = absent_symbol_problems(
        labelled_frame(["BTCUSDT", None], [1.0, 2.0]), UNIVERSE
    )
    assert [p.kind for p in problems] == ["non_string_symbol_label"]
    assert problems[0].symbol is None
    assert "None" in problems[0].message


def test_an_explicitly_empty_label_is_malformed():
    problems = absent_symbol_problems(labelled_frame([""], [1.0]), ("",))
    assert [p.kind for p in problems] == ["non_string_symbol_label"]


def test_the_case_where_the_universe_is_empty_and_truth_is_irrelevant():
    # An empty universe lists nothing, so any label at all is absent from it.
    problems = absent_symbol_problems(pl.Series("BTCUSDT", [0.1]), ())
    assert [p.symbol for p in problems] == ["BTCUSDT"]


def test_an_empty_universe_and_an_unlabelled_return_are_both_silent():
    assert absent_symbol_problems(pl.Series("score", dtype=pl.Float64), ()) == []


def test_a_window_object_is_accepted_for_its_universe():
    assert absent_symbol_problems(pl.Series("DOGEUSDT", [0.3]), Window(UNIVERSE))[
        0
    ].symbol == "DOGEUSDT"


def test_a_bare_string_universe_is_refused_by_name():
    # Iterating "BTCUSDT" yields one "symbol" per character, which would look
    # plausible and be silently wrong — the same refusal `window._as_universe`
    # makes.
    with pytest.raises(TypeError, match="not a single string"):
        universe_symbols("BTCUSDT")


def test_universe_symbols_reads_a_window_and_a_collection_alike():
    assert universe_symbols(Window(UNIVERSE)) == UNIVERSE
    assert universe_symbols(UNIVERSE) == UNIVERSE
    assert universe_symbols(["A", "B"]) == ("A", "B")


# --------------------------------------------------------------------------
# The outcome — what the run records
# --------------------------------------------------------------------------


def test_a_conforming_return_emits_ok():
    outcome = check_signal_return(pl.Series("score", [0.1, -0.2, 0.5]), UNIVERSE)
    assert isinstance(outcome, SignalReturnOutcome)
    assert outcome.outcome == OUTCOME_OK
    assert outcome.ok and not outcome.violated
    assert outcome.problems == ()


def test_an_absent_symbol_emits_contract_violation():
    outcome = check_signal_return(pl.Series("DOGEUSDT", [0.3]), ("BTCUSDT",))
    assert outcome.outcome == CONTRACT_VIOLATION
    assert outcome.violated and not outcome.ok
    assert outcome.absent_symbols == ("DOGEUSDT",)


def test_an_absent_symbol_in_a_frame_emits_contract_violation():
    outcome = check_signal_return(
        labelled_frame(["BTCUSDT", "DOGEUSDT"], [1.0, 2.0]), UNIVERSE
    )
    assert outcome.outcome == CONTRACT_VIOLATION
    assert outcome.absent_symbols == ("DOGEUSDT",)


def test_a_labeled_but_correct_frame_still_reports_its_shape_problem():
    # Composition, not replacement: a correctly-labeled DataFrame satisfies
    # feature 12's label check and still violates feature 11's carrier check.
    # Reporting both is what tells an author that fixing the labels alone
    # will not make the return conform.
    outcome = check_signal_return(labelled_frame(UNIVERSE, [1.0, 2.0, 3.0]), UNIVERSE)
    assert outcome.outcome == CONTRACT_VIOLATION
    assert outcome.absent_symbols == ()
    assert [p.kind for p in outcome.problems] == ["not_a_series"]


def test_index_problems_lead_the_problem_list():
    # An absent-symbol problem says *which score is misattributed*, which is
    # more actionable than the shape complaint beside it.
    outcome = check_signal_return(
        labelled_frame(["DOGEUSDT", "ETHUSDT"], [1.0, 2.0]), UNIVERSE
    )
    assert [p.kind for p in outcome.problems] == [
        "absent_symbol",
        "not_a_series",
    ]


def test_a_struct_return_reports_both_halves():
    outcome = check_signal_return(
        labelled_struct(["BTCUSDT", "DOGEUSDT"], [1.0, 2.0]), UNIVERSE
    )
    assert outcome.outcome == CONTRACT_VIOLATION
    assert outcome.absent_symbols == ("DOGEUSDT",)
    # Two symbols' labels against a three-symbol universe, and a struct is
    # not a float series — the label check and the carrier check both fire.
    assert [p.kind for p in outcome.problems] == [
        "absent_symbol",
        "non_float_dtype",
        "wrong_length",
    ]


def test_absent_symbols_are_sorted_and_deduplicated():
    # The field a human reads at a glance, and compares as a set — so it does
    # not depend on where in the frame the strangers appeared, and a symbol
    # repeated across rows is still one symbol.
    outcome = check_signal_return(
        labelled_frame(["SHIBUSDT", "DOGEUSDT", "SHIBUSDT"], [1.0, 2.0, 3.0]),
        UNIVERSE,
    )
    assert outcome.absent_symbols == ("DOGEUSDT", "SHIBUSDT")


def test_the_claimed_index_is_recorded_verbatim_and_in_order():
    outcome = check_signal_return(
        labelled_frame(["SHIBUSDT", "BTCUSDT"], [1.0, 2.0]), UNIVERSE
    )
    assert outcome.index == ("SHIBUSDT", "BTCUSDT")


def test_a_conforming_return_records_an_empty_index():
    # "This return made no symbol claim" is readable off the record rather
    # than inferred from an empty problem list.
    assert check_signal_return(
        pl.Series("score", [0.1, 0.2, 0.3]), UNIVERSE
    ).index == ()


def test_a_non_string_label_is_recorded_as_a_violation():
    outcome = check_signal_return(labelled_frame([7], [1.0]), ("7",))
    assert outcome.outcome == CONTRACT_VIOLATION
    assert outcome.absent_symbols == ()
    assert [p.kind for p in outcome.problems] == [
        "non_string_symbol_label",
        "not_a_series",
    ]


def test_a_wrong_length_return_still_reports_its_labels():
    # The two halves are independent: a length mismatch stops feature 11's
    # per-value checks but says nothing about which symbols were claimed.
    outcome = check_signal_return(pl.Series("DOGEUSDT", [0.1, 0.2]), UNIVERSE)
    assert outcome.absent_symbols == ("DOGEUSDT",)
    assert [p.kind for p in outcome.problems] == ["absent_symbol", "wrong_length"]


def test_the_outcome_is_a_value_and_never_a_raise():
    # Every refusal in this package is a value, because the caller knows what
    # a bad return costs (a retry, a trial charge, a discard).
    for bad in (None, "not a series", [0.1], pl.DataFrame({"symbol": [1]})):
        outcome = check_signal_return(bad, UNIVERSE)
        assert outcome.outcome == CONTRACT_VIOLATION


def test_the_outcome_is_deterministic():
    bad = pl.Series("DOGEUSDT", [0.3])
    assert check_signal_return(bad, UNIVERSE) == check_signal_return(bad, UNIVERSE)


def test_the_outcome_is_frozen():
    outcome = check_signal_return(pl.Series("DOGEUSDT", [0.3]), UNIVERSE)
    with pytest.raises(Exception):  # frozen: cannot be mutated after construction
        outcome.outcome = OUTCOME_OK  # type: ignore[misc]


def test_the_outcome_serializes_to_a_json_ready_record():
    outcome = check_signal_return(pl.Series("DOGEUSDT", [0.3]), ("BTCUSDT",))
    record = outcome.as_record()
    assert record["outcome"] == "contract_violation"
    assert record["absent_symbols"] == ["DOGEUSDT"]
    assert record["index"] == ["DOGEUSDT"]
    assert record["problems"][0]["kind"] == "absent_symbol"
    assert record["problems"][0]["symbol"] == "DOGEUSDT"
    import json

    json.dumps(record)  # the record is what a run persists, so it must be plain


def test_an_ok_outcome_serializes_with_empty_lists():
    record = check_signal_return(pl.Series("score", [0.1, 0.2, 0.3]), UNIVERSE).as_record()
    assert record == {
        "outcome": "ok",
        "index": [],
        "absent_symbols": [],
        "problems": [],
    }


# --------------------------------------------------------------------------
# The end-to-end rejection: a real signal, its claim, and the outcome
# --------------------------------------------------------------------------


def test_a_window_universe_composed_by_the_factory_is_accepted():
    # The seam that matters: `universe_symbols` ducks the `universe` attribute
    # rather than `isinstance`-ing the window class, so a window built by the
    # real contract — not the stand-in above — is read the same way.
    from contract import MarketWindow

    window = MarketWindow(t="2026-06-15T12:00:00+00:00", universe=UNIVERSE)
    assert check_signal_return(pl.Series("score", [0.1, 0.2, 0.3]), window).ok
    violation = check_signal_return(pl.Series("DOGEUSDT", [0.1]), window)
    assert violation.outcome == CONTRACT_VIOLATION
    assert violation.absent_symbols == ("DOGEUSDT",)


def test_a_signal_that_returns_a_bare_series_conforms():
    code = """
import polars as pl

def signal(ctx, seed):
    return pl.Series("score", [0.5, -0.5, 0.0])
"""
    namespace: dict = {}
    exec(compile(code, "<t>", "exec"), namespace)
    result = namespace["signal"](Window(UNIVERSE), 0)
    assert check_signal_return(result, UNIVERSE).outcome == OUTCOME_OK


def test_a_signal_that_returns_a_frame_of_strangers_is_rejected():
    code = """
import polars as pl

def signal(ctx, seed):
    return pl.DataFrame({"symbol": ["DOGEUSDT"], "score": [0.9]})
"""
    namespace: dict = {}
    exec(compile(code, "<t>", "exec"), namespace)
    result = namespace["signal"](Window(("BTCUSDT",)), 0)
    outcome = check_signal_return(result, ("BTCUSDT",))
    assert outcome.outcome == "contract_violation"
    assert outcome.absent_symbols == ("DOGEUSDT",)


# --------------------------------------------------------------------------
# The layering note: this module must not make polars a composition cost
# --------------------------------------------------------------------------


def test_importing_the_package_does_not_import_polars():
    # The contract package is imported by the application factory's workspace
    # scan, so a module-scope `import polars` anywhere in it would make polars
    # a precondition for *composing the application*.  Asserted in a
    # subprocess, because this suite's own imports have already loaded polars
    # into this interpreter.
    #
    # PYTHONPATH is set from the repo layout rather than inherited, so the
    # check does not silently depend on the workspace member having been
    # installed into the venv (`uv sync --all-packages`); a bare `uv run`
    # installs only the root project, and the seam under test is exactly the
    # one that must survive that.
    script = (
        "import sys; import contract, contract.violation;"
        "assert 'polars' not in sys.modules, 'polars imported at module scope';"
        "print('deferred')"
    )
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            [
                str(REPO_ROOT / "src"),
                str(REPO_ROOT / "packages" / "contract" / "src"),
                os.environ.get("PYTHONPATH", ""),
            ]
        ),
    }
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "deferred" in result.stdout
