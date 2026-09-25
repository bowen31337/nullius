"""Feature 327: the observation window an auto-demotion must be taken over.

The suite is organised around the sentence's claims, because they are the
things that can silently stop being true:

* **A window that has reached the minimum is meaningful.**  The boundary
  is pinned exactly, not approximated: ``observed_days`` equal to the
  requirement is *at* it (the PRD's own *"at 90 days"* reading of *at*),
  one day short is thin, and the thin side is strictly below.
* **The window is handed over, never derived.**  The seam takes the
  observed-day count and the requirement — nothing else — and the module
  names no forward column.  The cross-member test proves the count
  travels beside the ratio through the forward member's public seam: a
  real second interpreter's young record is rejected through the count
  that member computed, and the same record, grown by another process to
  the requirement, then demotes.
* **The window is judged only once the ratio has fired.**  A held ratio
  answers ``None`` with the window moot — a young signal the feature is
  happy with must not raise — while the counts' own terms are validated
  on every call regardless.
* **A demotion on a thin sample is rejected, loudly.**  A typed refusal
  carrying the window it judged, greppable by its token, writing no row
  and opening no store — and a rejection that lifts by itself as the
  record accrues days.
* **A meaningful window demotes exactly as feature 326 did.**  By
  delegating wholesale: the row that lands is 326's five facts,
  first-write-wins and all, and the no-store refusal once the demotion
  has fired is 326's own.

The refusals are the sixth subject: a count that is not a whole positive
number (``bool`` first), a minimum that states no requirement (zero is a
gate open at every sample), and the ordering of the judgements — the
counts before feature 326's terms, the window before the store, the
rejection before anything is opened.  Each in its own class, each named
by the grep token its messages open with.
"""

from __future__ import annotations

import inspect
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
from risk._identity import process_identity
from risk.demotion import (
    DATABASE_URL_ENV,
    DEMOTION_BOUND,
    RISK_SIGNAL_DEMOTION_TABLE,
    RiskSignalDemotionStore,
)
from risk.demotion_window import (
    DemotionWindow,
    demote_over_meaningful_window,
)
from risk.errors import (
    DEMOTION_WINDOW_CODE,
    RiskDemotionWindowError,
    RiskError,
    RiskSignalDemotionError,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

#: A node that is a signal identity — a UUID — so the node validation
#: passes and the tests exercise the window's judgements.
NODE = "11111111-1111-1111-1111-111111111111"
#: A node that is not a UUID at all — 326's malformed-ask refusal.
NOT_A_NODE = "not-a-signal-identity"

#: A ratio below the bound (a demotion would fire), at the bound (held),
#: and above it (held).  The 0.4 is pinned exactly, as in 326's suite.
BELOW_BOUND = 0.2
AT_BOUND = 0.4
ABOVE_BOUND = 0.6

#: The window a deployment might state — thirty observed days.  The number
#: is arbitrary to this suite on purpose: the spec names *"statistically
#: meaningful"* and no number, so the requirement is the caller's to
#: state, and the tests state different ones where the boundary matters.
MINIMUM = 30
#: Two observed days — a record in its first week, and a thin sample
#: against any window stated in tens of days.
THIN = 2


def _row_count(database_url: str) -> int:
    """How many demotion rows the table holds, read with the driver directly.

    Restated rather than imported from 326's suite, so these tests measure
    the table rather than a copy of the helper that reads it — and so a
    rejection's ``0`` is the count in the database, not the absence of an
    exception.
    """
    path = database_url.removeprefix("sqlite:///")
    try:
        with closing(sqlite3.connect(path)) as connection:
            (count,) = connection.execute(
                f"SELECT COUNT(*) FROM {RISK_SIGNAL_DEMOTION_TABLE}"
            ).fetchone()
    except sqlite3.OperationalError:
        return 0
    return count


def _seed(url: str, script: str) -> None:
    """Run a seeding script in a real second interpreter.

    The same road 326's cross-member test takes: every declared member's
    scan root on the path, exactly as the production loader and this
    suite's conftest do, so the seed drives the real promotion and forward
    members rather than a fixture's shorthand for them.
    """
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            [
                str(REPO_ROOT / "src"),
                *(str(p) for p in sorted((REPO_ROOT / "packages").glob("*/src"))),
                os.environ.get("PYTHONPATH", ""),
            ]
        ),
    }
    result = subprocess.run(
        [sys.executable, "-c", script, url],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


# -- The boundary -----------------------------------------------------------------


class TestTheWindowBoundary:
    def test_a_window_at_the_minimum_is_meaningful(self) -> None:
        # A record that has observed exactly the required number of days
        # *has* a window of that many days: the requirement is met at the
        # boundary, not past it — the PRD's own "at 90 days" reading of
        # "at".  Pinned exactly, not approximated.
        window = DemotionWindow(observed_days=MINIMUM, minimum_observed_days=MINIMUM)
        assert window.meaningful is True
        assert window.thin is False
        assert window.days_short == 0

    def test_a_window_one_day_short_is_thin(self) -> None:
        # The thin side is strictly below — the workspace's boundary
        # convention beside 326's strict `<` on the ratio.
        window = DemotionWindow(
            observed_days=MINIMUM - 1, minimum_observed_days=MINIMUM
        )
        assert window.thin is True
        assert window.meaningful is False
        assert window.days_short == 1

    def test_days_short_never_answers_negative(self) -> None:
        # A window that has passed its requirement is not "short by a
        # negative number"; the property is arithmetic over the counts and
        # clamps at zero, so a caller logging it never prints a shortfall
        # for a window that has none.
        window = DemotionWindow(
            observed_days=MINIMUM + 40, minimum_observed_days=MINIMUM
        )
        assert window.days_short == 0
        assert window.meaningful is True

    def test_the_window_is_frozen(self) -> None:
        # A value, not a mutable record: the window the rejection carried
        # and the window the caller stated are one object that cannot be
        # edited after the fact.
        window = DemotionWindow(observed_days=THIN, minimum_observed_days=MINIMUM)
        with pytest.raises(FrozenInstanceError):
            window.observed_days = MINIMUM  # type: ignore[misc]

    def test_the_judgement_is_derived_not_stored(self) -> None:
        # `meaningful` and `thin` are properties over the two counts, so a
        # window cannot disagree with its own numbers, and two windows
        # built from the same counts are the same window.
        assert DemotionWindow(THIN, MINIMUM) == DemotionWindow(THIN, MINIMUM)
        assert DemotionWindow(THIN, MINIMUM) != DemotionWindow(MINIMUM, MINIMUM)


# -- The counts' own terms --------------------------------------------------------


class TestTheCountsOwnTerms:
    @pytest.mark.parametrize("observed_days", [True, False])
    def test_a_bool_observed_count_is_refused_by_name(
        self, observed_days: bool
    ) -> None:
        # `isinstance(True, int)` is true in Python, so a naive numeric
        # check would put a one-day window behind a demotion nobody meant
        # to vouch for.
        with pytest.raises(RiskDemotionWindowError) as refused:
            demote_over_meaningful_window(
                NODE,
                ratio=BELOW_BOUND,
                observed_days=observed_days,
                minimum_observed_days=MINIMUM,
                env={},
            )
        assert DEMOTION_WINDOW_CODE in str(refused.value)
        assert "bool" in str(refused.value)

    @pytest.mark.parametrize("observed_days", [30.0, "30", None, 30.5])
    def test_an_observed_count_that_is_not_whole_is_refused(
        self, observed_days: object
    ) -> None:
        # The count is how many days carried a measurement; a fraction or
        # a word is not a count of days, and the forward member's own
        # count is whole by construction.
        with pytest.raises(RiskDemotionWindowError) as refused:
            demote_over_meaningful_window(
                NODE,
                ratio=BELOW_BOUND,
                observed_days=observed_days,
                minimum_observed_days=MINIMUM,
                env={},
            )
        assert "whole number" in str(refused.value)

    @pytest.mark.parametrize("observed_days", [0, -5])
    def test_an_absent_observation_is_refused_not_answered_thin(
        self, observed_days: int
    ) -> None:
        # A signal with no observed day has no live coefficient for a
        # retention ratio to have been taken over at all — the forward
        # member refuses that state earlier, by name, so a zero reaching
        # here is a caller asserting an absence the seam it claims to have
        # read already refuses.  "Thin" is a judgement about a window that
        # exists; this is not one.
        with pytest.raises(RiskDemotionWindowError) as refused:
            demote_over_meaningful_window(
                NODE,
                ratio=BELOW_BOUND,
                observed_days=observed_days,
                minimum_observed_days=MINIMUM,
                env={},
            )
        assert "at least 1" in str(refused.value)

    @pytest.mark.parametrize("minimum", [True, False])
    def test_a_bool_minimum_is_refused_by_name(self, minimum: bool) -> None:
        with pytest.raises(RiskDemotionWindowError) as refused:
            demote_over_meaningful_window(
                NODE,
                ratio=BELOW_BOUND,
                observed_days=THIN,
                minimum_observed_days=minimum,
                env={},
            )
        assert "bool" in str(refused.value)

    @pytest.mark.parametrize("minimum", [90.0, "90", None])
    def test_a_minimum_that_is_not_whole_is_refused(self, minimum: object) -> None:
        # The requirement is the deployment's spelling of "statistically
        # meaningful"; a window that is not one number is a line nobody
        # drew.
        with pytest.raises(RiskDemotionWindowError) as refused:
            demote_over_meaningful_window(
                NODE,
                ratio=BELOW_BOUND,
                observed_days=THIN,
                minimum_observed_days=minimum,
                env={},
            )
        assert "whole number" in str(refused.value)

    @pytest.mark.parametrize("minimum", [0, -1])
    def test_a_minimum_of_zero_is_a_gate_open_at_every_sample(
        self, minimum: int
    ) -> None:
        # Honouring a zero minimum would let the demotion fire on the
        # first day's noise while the record read as though a requirement
        # had been set and met — the absence of this feature wearing its
        # configuration.
        with pytest.raises(RiskDemotionWindowError) as refused:
            demote_over_meaningful_window(
                NODE,
                ratio=BELOW_BOUND,
                observed_days=THIN,
                minimum_observed_days=minimum,
                env={},
            )
        message = str(refused.value)
        assert "at least 1" in message
        assert "first day's noise" in message

    def test_the_value_layer_refuses_on_any_construction(self) -> None:
        # The gate is the seam, but the law is the value's: a window built
        # directly with a malformed count is refused there too, so nothing
        # downstream of the value can be handed one.
        with pytest.raises(RiskDemotionWindowError):
            DemotionWindow(observed_days=THIN, minimum_observed_days=0)
        with pytest.raises(RiskDemotionWindowError):
            DemotionWindow(observed_days=True, minimum_observed_days=MINIMUM)


# -- The order of the judgements --------------------------------------------------


class TestTheOrderOfJudgement:
    def test_a_held_ratio_answers_none_with_the_window_moot(self) -> None:
        # The sentence requires the window "before auto-demotion fires",
        # and a held ratio is not a demotion firing.  A supervisor
        # sweeping every cycle must not raise on the young signals it is
        # happy with, or the operator's log teaches them to ignore the
        # token.
        assert (
            demote_over_meaningful_window(
                NODE,
                ratio=ABOVE_BOUND,
                observed_days=THIN,
                minimum_observed_days=MINIMUM,
                env={},
            )
            is None
        )

    def test_a_ratio_at_the_bound_is_held_with_the_window_moot(self) -> None:
        # 326's boundary, inherited unchanged by the gated seam: exactly
        # at 0.4 the signal is held, thin window or not.
        assert (
            demote_over_meaningful_window(
                NODE,
                ratio=AT_BOUND,
                observed_days=THIN,
                minimum_observed_days=MINIMUM,
                env={},
            )
            is None
        )

    def test_a_held_ratio_leaves_no_row(self, test_database_url: str) -> None:
        assert (
            demote_over_meaningful_window(
                NODE,
                ratio=ABOVE_BOUND,
                observed_days=THIN,
                minimum_observed_days=MINIMUM,
                database_url=test_database_url,
            )
            is None
        )
        assert _row_count(test_database_url) == 0

    def test_the_counts_are_validated_even_when_the_ratio_is_held(self) -> None:
        # A caller that cannot state its evidence cannot be told it was
        # happy: the malformed ask is refused whether or not the ratio
        # fired, so a held ratio never launders a count nobody could have
        # read off the forward member's answer.
        with pytest.raises(RiskDemotionWindowError):
            demote_over_meaningful_window(
                NODE,
                ratio=ABOVE_BOUND,
                observed_days=None,
                minimum_observed_days=MINIMUM,
                env={},
            )

    def test_the_windows_terms_are_judged_before_feature_326s(self) -> None:
        # The window is this feature's structural ask, so it is judged
        # first: a call malformed in both counts names the count, not the
        # ratio — the caller learns which half of its ask to fix.
        with pytest.raises(RiskDemotionWindowError) as refused:
            demote_over_meaningful_window(
                NODE,
                ratio="below",  # type: ignore[arg-type]
                observed_days=THIN,
                minimum_observed_days=0,
                env={},
            )
        assert DEMOTION_WINDOW_CODE in str(refused.value)

    def test_a_thin_sample_is_rejected_before_the_store_is_demanded(self) -> None:
        # Nothing was demoted, so there is nothing to account for: the
        # rejection needs no store, and a deployment that names none still
        # gets the window's refusal — not 326's no-store refusal, which is
        # about a *fired* demotion with nowhere to record it and names
        # DATABASE_URL in every message it raises.
        with pytest.raises(RiskDemotionWindowError) as refused:
            demote_over_meaningful_window(
                NODE,
                ratio=BELOW_BOUND,
                observed_days=THIN,
                minimum_observed_days=MINIMUM,
                env={},
            )
        message = str(refused.value)
        assert "thin sample" in message
        assert DATABASE_URL_ENV not in message

    def test_a_meaningful_firing_ratio_with_no_store_is_326s_refusal(self) -> None:
        # The window passed and the demotion fired, so from this moment
        # the signal is demoted and nothing would record why — 326's own
        # refusal, in 326's own words, reached one judgement later.
        with pytest.raises(RiskSignalDemotionError) as refused:
            demote_over_meaningful_window(
                NODE,
                ratio=BELOW_BOUND,
                observed_days=MINIMUM,
                minimum_observed_days=MINIMUM,
                env={},
            )
        assert "signal_demotion" in str(refused.value)

    def test_a_held_ratio_with_no_store_needs_nothing(self) -> None:
        # The held answer inherited whole: no window, no store, no error.
        assert (
            demote_over_meaningful_window(
                NODE,
                ratio=ABOVE_BOUND,
                observed_days=MINIMUM,
                minimum_observed_days=MINIMUM,
                env={},
            )
            is None
        )


# -- The rejection ----------------------------------------------------------------


class TestTheRejection:
    def test_a_firing_ratio_over_a_thin_sample_is_rejected(
        self, test_database_url: str
    ) -> None:
        # The demotion the caller asked for would have fired, and the
        # rejection says so — naming the days seen, the days required, and
        # the ratio that fell — rather than folding "fine" and "unproven"
        # into one silent None.
        with pytest.raises(RiskDemotionWindowError) as refused:
            demote_over_meaningful_window(
                NODE,
                ratio=BELOW_BOUND,
                observed_days=THIN,
                minimum_observed_days=MINIMUM,
                database_url=test_database_url,
            )
        message = str(refused.value)
        assert message.startswith(DEMOTION_WINDOW_CODE)
        assert "thin sample" in message
        assert f"{THIN} observed" in message
        assert f"{MINIMUM} the deployment requires" in message
        assert "28 short" in message
        assert repr(BELOW_BOUND) in message

    def test_the_rejection_carries_the_window_it_judged(self) -> None:
        # The operator paging on a withheld demotion asks how much was
        # seen and against what requirement first, and the refusal is
        # where they look for it — the same stance the killed and stale
        # receipts take toward the values they carry.
        with pytest.raises(RiskDemotionWindowError) as refused:
            demote_over_meaningful_window(
                NODE,
                ratio=BELOW_BOUND,
                observed_days=THIN,
                minimum_observed_days=MINIMUM,
                env={},
            )
        assert refused.value.window == DemotionWindow(THIN, MINIMUM)
        assert refused.value.window is not None
        assert refused.value.window.thin is True

    def test_the_malformed_asks_carry_no_window(self) -> None:
        # The counts could not be constructed into a window, so there is
        # nothing to carry — and `None` there is the honest absence, not a
        # missing payload on a rejection that judged one.
        with pytest.raises(RiskDemotionWindowError) as refused:
            demote_over_meaningful_window(
                NODE,
                ratio=BELOW_BOUND,
                observed_days=THIN,
                minimum_observed_days=0,
                env={},
            )
        assert refused.value.window is None

    def test_a_rejection_writes_no_row_and_opens_no_store(self, tmp_path: Path) -> None:
        # Nothing was demoted, so nothing is on record — and a judgement
        # that costs no I/O must not touch the disk: the database the
        # rejection was pointed at is never even created.
        database = tmp_path / "never-opened.db"
        url = f"sqlite:///{database}"
        with pytest.raises(RiskDemotionWindowError):
            demote_over_meaningful_window(
                NODE,
                ratio=BELOW_BOUND,
                observed_days=THIN,
                minimum_observed_days=MINIMUM,
                database_url=url,
            )
        assert not database.exists()
        assert _row_count(url) == 0

    def test_the_rejection_is_catchable_by_the_members_base(self) -> None:
        # Every face of the feature is catchable by the one base, so a
        # supervisor wrapping its whole demotion path catches them all.
        with pytest.raises(RiskError):
            demote_over_meaningful_window(
                NODE,
                ratio=BELOW_BOUND,
                observed_days=THIN,
                minimum_observed_days=MINIMUM,
                env={},
            )

    def test_the_boundary_pair_one_day_apart(self, test_database_url: str) -> None:
        # Twenty-nine days short of thirty is rejected; thirty is not.
        # The whole feature in two calls one day apart.
        with pytest.raises(RiskDemotionWindowError):
            demote_over_meaningful_window(
                NODE,
                ratio=BELOW_BOUND,
                observed_days=MINIMUM - 1,
                minimum_observed_days=MINIMUM,
                database_url=test_database_url,
            )
        landed = demote_over_meaningful_window(
            NODE,
            ratio=BELOW_BOUND,
            observed_days=MINIMUM,
            minimum_observed_days=MINIMUM,
            database_url=test_database_url,
        )
        assert landed is not None
        assert _row_count(test_database_url) == 1

    def test_the_rejection_lifts_as_the_record_accrues_days(
        self, test_database_url: str
    ) -> None:
        # The rejection is not a state and nobody clears it: the same
        # call, re-judged as the count grows, stops being refused by
        # itself — the same shape the staleness watchdog gives its
        # refusal, and for the same reason.
        for seen in (THIN, MINIMUM - 1, MINIMUM):
            if seen < MINIMUM:
                with pytest.raises(RiskDemotionWindowError):
                    demote_over_meaningful_window(
                        NODE,
                        ratio=BELOW_BOUND,
                        observed_days=seen,
                        minimum_observed_days=MINIMUM,
                        database_url=test_database_url,
                    )
            else:
                landed = demote_over_meaningful_window(
                    NODE,
                    ratio=BELOW_BOUND,
                    observed_days=seen,
                    minimum_observed_days=MINIMUM,
                    database_url=test_database_url,
                )
                assert landed is not None
                assert landed.changed is True


# -- The delegation ---------------------------------------------------------------


class TestTheDelegation:
    def test_a_meaningful_window_lands_326s_row(self, test_database_url: str) -> None:
        # The gated seam persists exactly what 326's would have: the
        # ratio, the bound, the moment read back from the standing row,
        # and this process's kernel-read identity.
        record = demote_over_meaningful_window(
            NODE,
            ratio=BELOW_BOUND,
            observed_days=MINIMUM,
            minimum_observed_days=MINIMUM,
            database_url=test_database_url,
        )
        assert record is not None
        assert record.changed is True
        assert record.node_id == NODE
        assert record.ratio == BELOW_BOUND
        assert record.bound == DEMOTION_BOUND
        assert record.supervisor_process_id == process_identity()
        assert _row_count(test_database_url) == 1

    def test_the_delegation_can_be_driven_through_the_store_face(
        self, test_database_url: str
    ) -> None:
        # The row the gated seam writes is the row 326's own reader
        # sweeps: one table, one spelling of what a demotion is, and the
        # window left no second mark on it.
        demote_over_meaningful_window(
            NODE,
            ratio=BELOW_BOUND,
            observed_days=MINIMUM,
            minimum_observed_days=MINIMUM,
            database_url=test_database_url,
        )
        (standing,) = RiskSignalDemotionStore(test_database_url).demotions()
        assert standing.ratio == BELOW_BOUND
        assert standing.changed is False

    def test_first_write_wins_is_inherited_wholesale(
        self, test_database_url: str
    ) -> None:
        # A re-filing over a meaningful window writes nothing and returns
        # the standing demotion — 326's retry law, inherited by
        # delegation rather than restated (a second spelling of it would
        # be a second way for two demotions of one signal to disagree).
        first = demote_over_meaningful_window(
            NODE,
            ratio=BELOW_BOUND,
            observed_days=MINIMUM,
            minimum_observed_days=MINIMUM,
            database_url=test_database_url,
        )
        again = demote_over_meaningful_window(
            NODE,
            ratio=BELOW_BOUND - 0.1,
            observed_days=MINIMUM + 10,
            minimum_observed_days=MINIMUM,
            database_url=test_database_url,
        )
        assert first is not None and again is not None
        assert again.changed is False
        assert again.ratio == first.ratio
        assert again.demoted_at == first.demoted_at
        assert _row_count(test_database_url) == 1

    def test_the_environment_names_the_store_when_no_url_does(
        self, test_database_url: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(DATABASE_URL_ENV, test_database_url)
        record = demote_over_meaningful_window(
            NODE,
            ratio=BELOW_BOUND,
            observed_days=MINIMUM,
            minimum_observed_days=MINIMUM,
        )
        assert record is not None
        assert _row_count(test_database_url) == 1

    def test_an_explicit_url_wins_over_the_environment(
        self, test_database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(DATABASE_URL_ENV, f"sqlite:///{tmp_path / 'ignored.db'}")
        record = demote_over_meaningful_window(
            NODE,
            ratio=BELOW_BOUND,
            observed_days=MINIMUM,
            minimum_observed_days=MINIMUM,
            database_url=test_database_url,
        )
        assert record is not None
        assert _row_count(test_database_url) == 1

    def test_a_custom_bound_travels_to_the_delegation(
        self, test_database_url: str
    ) -> None:
        # The window gates 326's comparison; it does not replace it.  A
        # deployment that retunes the bound still has it judged, and the
        # row stores the bound that fired: the same ratio is held against
        # the default 0.4 and demoted against a looser 0.5.
        held = demote_over_meaningful_window(
            NODE,
            ratio=0.45,
            observed_days=MINIMUM,
            minimum_observed_days=MINIMUM,
            database_url=test_database_url,
        )
        assert held is None
        landed = demote_over_meaningful_window(
            NODE,
            ratio=0.45,
            observed_days=MINIMUM,
            minimum_observed_days=MINIMUM,
            bound=0.5,
            database_url=test_database_url,
        )
        assert landed is not None
        assert landed.bound == 0.5

    def test_a_node_that_is_not_a_signal_identity_is_326s_refusal(self) -> None:
        # The node, the ratio and the bound are validated through 326's
        # own validators, so one spelling of what those terms are decides
        # both seams — and the refusal is 326's class, not this feature's.
        with pytest.raises(RiskSignalDemotionError) as refused:
            demote_over_meaningful_window(
                NOT_A_NODE,
                ratio=BELOW_BOUND,
                observed_days=MINIMUM,
                minimum_observed_days=MINIMUM,
                env={},
            )
        assert "signal identity" in str(refused.value)


# -- The hand-over ----------------------------------------------------------------


class TestTheHandOver:
    def test_the_seam_takes_the_counts_not_the_record(self) -> None:
        # The supervisor hands over the signal's identity, the ratio, the
        # observed-day count and the requirement — nothing else.  The seam
        # does not name the forward member's columns and does not reach
        # into its tables: a member never imports a sibling's tables.
        parameters = set(inspect.signature(demote_over_meaningful_window).parameters)
        assert {"node_id", "ratio", "observed_days", "minimum_observed_days"} <= (
            parameters
        )
        assert "live_ic" not in parameters
        assert "backtest_ic" not in parameters

    def test_the_minimum_is_a_required_keyword_with_no_default(self) -> None:
        # The spec names "statistically meaningful" and no number, so the
        # requirement is the deployment's to state: a supervisor that
        # guessed a window would demote on a track record nobody vouched
        # for.  The signature states the absence of a default.
        parameter = inspect.signature(demote_over_meaningful_window).parameters[
            "minimum_observed_days"
        ]
        assert parameter.default is inspect.Parameter.empty
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY

    def test_the_module_never_names_the_forward_columns(self) -> None:
        # The count reaches the ratio through the forward member's public
        # answer, never by reading the record itself.  The module's source
        # names no forward column.
        source = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "risk"
            / ("demotion_window.py")
        )
        text = source.read_text()
        assert "live_ic" not in text
        assert "backtest_ic" not in text
        assert "forward_record" not in text

    def test_the_module_reads_no_clock(self) -> None:
        # The window is a count of days handed over, not a span this
        # module measures between two instants: the days were already
        # counted by the member that observed them, and a second counting
        # would be a second opinion about evidence this module decided not
        # to derive.  The module imports nothing from datetime at all.
        source = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "risk"
            / ("demotion_window.py")
        )
        text = source.read_text()
        assert "from datetime import" not in text
        assert "import datetime" not in text

    def test_the_gate_registers_no_fifth_builder(self) -> None:
        # The window owns no table and no state an application could
        # carry, so nothing is registered beside the member's four
        # components — the supervisor reaches the module-level spelling
        # without composing, exactly as it reaches the demotion.
        import risk as member

        assert [name for name in dir(member) if name.startswith("build_")] == [
            "build_halt_event_store",
            "build_risk_flattener",
            "build_risk_halt",
            "build_risk_kill_switch",
        ]

    def test_a_young_record_computed_by_another_process_is_rejected_then_grown(
        self, tmp_path: Path
    ) -> None:
        # The count travels beside the ratio through the forward member's
        # public seam, and this feature judges both.  A real second
        # interpreter drives the real promotion and forward members to a
        # two-day record; the retention it computed is handed over and the
        # demotion is rejected on the count that member stated; then a
        # second interpreter grows the same record to the requirement, and
        # the very same call fires.  The rejection lifted because the
        # record accrued days — no state was cleared.
        database = tmp_path / "cross-member.db"
        url = f"sqlite:///{database}"
        node = "11111111-1111-4111-8111-111111111111"
        seed_young = f"""
import sys
import datetime as dt

from promotion import PreRegistrations, PromotionCriteria
from promotion.decision import PromotionDecisions
from forward.record import ForwardRecords
from forward.observation import ForwardObservations
from forward.retention import ForwardIcRetentions

url = sys.argv[1]
node = {node!r}

# The discovery loop's writes: the node row, the sealed epoch, the promotion.
registrations = PreRegistrations(url)
registrations._connect().close()
connection = registrations._connect()
with connection:
    connection.execute(
        "INSERT INTO node (id, campaign_id, theme_root, depth) VALUES (?, ?, ?, ?)",
        (node, "22222222-2222-4222-8222-222222222222", "macro", 1),
    )
    connection.execute(
        "INSERT INTO epoch_ledger (epoch_id, sealed_at) VALUES (?, ?)",
        ("epoch-2026-01", "2026-01-01T00:00:00+00:00"),
    )
connection.close()
registrations.pre_register(
    node,
    "epoch-2026-01",
    PromotionCriteria(
        theta=0.3, alpha=0.05, max_fdr_deploy=0.25,
        min_worlds=50, min_coverage_strata=3, min_forward_days=90,
    ),
    clock=lambda: dt.datetime.fromisoformat("2026-02-01T00:00:00+00:00"),
)
PromotionDecisions(url).record_decision(
    node, decided_at=dt.datetime.fromisoformat("2026-03-01T12:00:00+00:00")
)

# Feature 332 opens the record; feature 333 appends the live IC observations;
# feature 337 lands the backtest coefficient.  Two days at a live IC of 0.1
# against a backtest of 0.5 give a retention ratio of 0.2 — below the bound,
# over a sample no window in tens of days would accept.
records = ForwardRecords(url)
records.open_record(node, forward_days=90)
observations = ForwardObservations.over(records)
observations.append_observation(
    node, observed_on=dt.date(2026, 3, 2), live_ic=0.1, forward_days=90
)
observations.append_observation(
    node, observed_on=dt.date(2026, 3, 3), live_ic=0.1, forward_days=90
)
ForwardIcRetentions.over(records).record_backtest_ic(node, backtest_ic=0.5)
"""
        seed_grown = f"""
import sys
import datetime as dt

from forward.record import ForwardRecords
from forward.observation import ForwardObservations

url = sys.argv[1]
node = {node!r}

# Twenty-eight more observed days — the same record, grown by another
# process, one row per day strictly after the boundary, to thirty.
records = ForwardRecords(url)
observations = ForwardObservations.over(records)
for day in range(4, 32):
    observations.append_observation(
        node,
        observed_on=dt.date(2026, 3, day),
        live_ic=0.1,
        forward_days=90,
    )
"""
        _seed(url, seed_young)

        # This process reads what that interpreter computed — through the
        # forward member's own public seam — and hands both figures over.
        from forward.retention import forward_ic_retention

        young = forward_ic_retention(node, database_url=url)
        assert young.observed_days == 2
        assert young.ratio == pytest.approx(0.1 / 0.5)
        with pytest.raises(RiskDemotionWindowError) as refused:
            demote_over_meaningful_window(
                young.node_id,
                ratio=young.ratio,
                observed_days=young.observed_days,
                minimum_observed_days=30,
                database_url=url,
            )
        assert refused.value.window is not None
        assert refused.value.window.observed_days == young.observed_days
        assert _row_count(url) == 0

        _seed(url, seed_grown)

        grown = forward_ic_retention(node, database_url=url)
        assert grown.observed_days == 30
        assert grown.ratio == pytest.approx(0.1 / 0.5)
        record = demote_over_meaningful_window(
            grown.node_id,
            ratio=grown.ratio,
            observed_days=grown.observed_days,
            minimum_observed_days=30,
            database_url=url,
        )
        assert record is not None
        assert record.changed is True
        assert record.ratio == pytest.approx(0.2)
        assert _row_count(url) == 1
