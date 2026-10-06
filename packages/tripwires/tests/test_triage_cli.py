"""Tests for ``python -m tripwires.triage`` (additions_spec_operator_surfaces.xml feature 5).

*"System runs the M1 triage experiment from `python -m tripwires.triage
[--seed S] [--count N]` and displays the perturbation-stability AUC with the
reading PRD §12 M1 assigns to it, or an error message with exit 1."*  The
command is a thin door onto :func:`tripwires.triage.run_triage`: parse the two
flags, call it, print its payload with one more field — the mean AUC's
reading — and exit 1 on the one refusal :func:`~tripwires.triage.run_triage`
itself can raise.

Two things are pinned here:

* **The reading rule**, against a *stubbed* figure rather than the real
  experiment.  The real planted population sits at chance (AUC ≈ 0.4548,
  see ``test_triage.py``), on neither side of either threshold, so the only
  way to exercise both branches of PRD §12's rule is to hand :func:`main`'s
  injectable ``runner`` seam a figure whose ``auc`` is chosen to sit there —
  at, above and below each bound, and in the open interval between them.
* **The refusal**, against the real :func:`~tripwires.triage.run_triage`,
  with a tiny ``--count`` so the test still runs in a fraction of a second:
  a count below two is refused before either population is even planted.

Every test passes under pytest-xdist: no module-level mutable state, no
database, no socket, and the one real ``run_triage()`` call below uses
``--count 2`` (the two-axes-both-classes floor), so it finishes in well
under a second rather than the pinned default's ~15 seconds.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from typing import Any

import pytest
from tripwires.errors import TripwirePanelError
from tripwires.triage import (
    EXIT_OK,
    EXIT_REFUSED,
    TRIAGE_LEARNED_SIGNATURE_AUC,
    TRIAGE_POPULATION_LABEL,
    TRIAGE_READING_INDETERMINATE,
    TRIAGE_READING_LEARNED_SIGNATURE,
    TRIAGE_READING_ROBUST_FILTER,
    TRIAGE_ROBUST_FILTER_AUC,
    main,
    run_triage,
    triage_reading,
)


@dataclass
class _StubFigure:
    """A minimal stand-in for :class:`~tripwires.triage.TriageFigure`.

    ``main`` reads exactly two things off whatever ``runner`` answers:
    ``.auc`` (to compute the reading) and ``.to_payload()`` (the JSON
    line's base). A stub carrying only those two is enough to drive the
    reading rule without paying for — or satisfying every invariant of — a
    real :class:`~tripwires.triage.TriageFigure`.
    """

    auc: float

    def to_payload(self) -> dict[str, Any]:
        return {"tripwire": "perturbation-stability", "auc": self.auc}


def _stub_runner(auc: float):
    def _runner(*, seed: int, count: int) -> _StubFigure:
        return _StubFigure(auc=auc)

    return _runner


# -- The reading rule, both thresholds, both sides ------------------------------


def test_the_thresholds_are_the_specs_own_numbers() -> None:
    assert TRIAGE_ROBUST_FILTER_AUC == 0.80
    assert TRIAGE_LEARNED_SIGNATURE_AUC == 0.65


@pytest.mark.parametrize("auc", [0.80, 0.81, 0.95, 1.0])
def test_the_robust_filter_reading_fires_at_and_above_its_bound(auc: float) -> None:
    assert triage_reading(auc) == TRIAGE_READING_ROBUST_FILTER


@pytest.mark.parametrize("auc", [0.65, 0.64, 0.40, 0.0])
def test_the_learned_signature_reading_fires_at_and_below_its_bound(
    auc: float,
) -> None:
    assert triage_reading(auc) == TRIAGE_READING_LEARNED_SIGNATURE


@pytest.mark.parametrize("auc", [0.66, 0.79, 0.725, 0.70])
def test_the_reading_is_indeterminate_strictly_between_the_bounds(
    auc: float,
) -> None:
    assert triage_reading(auc) == TRIAGE_READING_INDETERMINATE


# -- The CLI: the printed line, over a stubbed figure on each side --------------


@pytest.mark.parametrize(
    ("auc", "expected"),
    [
        (0.95, TRIAGE_READING_ROBUST_FILTER),
        (0.80, TRIAGE_READING_ROBUST_FILTER),
        (0.70, TRIAGE_READING_INDETERMINATE),
        (0.65, TRIAGE_READING_LEARNED_SIGNATURE),
        (0.40, TRIAGE_READING_LEARNED_SIGNATURE),
    ],
)
def test_main_prints_the_reading_for_a_stubbed_figure(
    auc: float, expected: str, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main([], runner=_stub_runner(auc))

    assert exit_code == EXIT_OK
    line = capsys.readouterr().out.strip()
    assert "\n" not in line  # exactly one JSON line
    payload = json.loads(line)
    assert payload["reading"] == expected
    assert payload["auc"] == auc


def test_main_prints_the_payload_plus_reading_and_population(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The spec's own shape: to_payload()'s own keys, untouched, plus exactly
    # the two this command adds.
    exit_code = main([], runner=_stub_runner(0.5))

    assert exit_code == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert set(payload) == {"tripwire", "auc", "reading", "population"}
    assert payload["population"] == TRIAGE_POPULATION_LABEL


def test_main_uses_the_injected_emit_instead_of_print() -> None:
    lines: list[str] = []
    exit_code = main([], emit=lines.append, runner=_stub_runner(0.9))

    assert exit_code == EXIT_OK
    assert len(lines) == 1
    assert json.loads(lines[0])["reading"] == TRIAGE_READING_ROBUST_FILTER


def test_seed_and_count_flags_reach_the_runner() -> None:
    seen: dict[str, int] = {}

    def _runner(*, seed: int, count: int) -> _StubFigure:
        seen["seed"] = seed
        seen["count"] = count
        return _StubFigure(auc=0.5)

    exit_code = main(["--seed", "7", "--count", "4"], runner=_runner, emit=lambda line: None)

    assert exit_code == EXIT_OK
    assert seen == {"seed": 7, "count": 4}


def test_the_defaults_match_the_module_constants() -> None:
    from tripwires.triage import TRIAGE_POPULATION, TRIAGE_SEED

    seen: dict[str, int] = {}

    def _runner(*, seed: int, count: int) -> _StubFigure:
        seen["seed"] = seed
        seen["count"] = count
        return _StubFigure(auc=0.5)

    main([], runner=_runner, emit=lambda line: None)

    assert seen == {"seed": TRIAGE_SEED, "count": TRIAGE_POPULATION}


# -- The refusal: a real run_triage(), a count too small to plant anything -----


def test_a_count_below_two_is_refused_with_exit_1_and_no_traceback(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The real run_triage() here, not a stub: the refusal fires before either
    # population is planted, so this is cheap regardless.
    exit_code = main(["--count", "1"])

    assert exit_code == EXIT_REFUSED
    captured = capsys.readouterr()
    assert captured.out == ""  # no JSON line on a refusal
    assert "Traceback" not in captured.err
    assert "at least two candidates" in captured.err


def test_a_non_integer_seed_is_refused_with_exit_1_not_argparses_exit_2(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The real run_triage() here too: a malformed --seed must reach its own
    # "seed is an integer" refusal (exit 1, this member's own text) rather
    # than being intercepted by argparse's usage error (exit 2) before
    # run_triage is ever called — argparse's own exit code is reserved for
    # a bad *flag*, not a bad *value* this member has its own word for.
    exit_code = main(["--seed", "not-an-int", "--count", "2"])

    assert exit_code == EXIT_REFUSED
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Traceback" not in captured.err
    assert "usage:" not in captured.err
    assert "integer" in captured.err
    assert "not-an-int" in captured.err


def test_a_numeric_seed_string_still_plants_the_pinned_population(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The flip side of the untyped --seed: "42" on the command line must
    # still reach run_triage as the int 42, not the string "42" (which
    # run_triage would itself refuse as non-integer).
    exit_code = main(["--seed", "42", "--count", "2"])

    assert exit_code == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["seed"] == 42


def test_the_refusal_text_is_the_panel_errors_own(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Pinned independently: whatever run_triage(count=0) raises is exactly
    # what reaches stderr, unchanged and un-wrapped.
    try:
        run_triage(count=0)
    except TripwirePanelError as exc:
        expected = str(exc)
    else:  # pragma: no cover - run_triage always refuses count=0
        pytest.fail("run_triage(count=0) did not raise TripwirePanelError")

    exit_code = main(["--count", "0"])

    assert exit_code == EXIT_REFUSED
    assert capsys.readouterr().err.strip() == expected


def test_a_runner_refusal_is_caught_the_same_way(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The catch is by error class, not by which argument was bad — a stubbed
    # "bad seed" refusal is caught identically to the real count refusal.
    def _refusing(*, seed: int, count: int) -> _StubFigure:
        raise TripwirePanelError(
            "the triage's seed is an integer, got 'not-a-seed'"
        )

    exit_code = main([], runner=_refusing)

    assert exit_code == EXIT_REFUSED
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Traceback" not in captured.err
    assert "seed is an integer" in captured.err


def test_the_run_reads_no_store_and_makes_no_network_call(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The real experiment, smallest legal population: two a side is enough to
    # plant both classes and run every axis, and it finishes in a fraction of
    # a second rather than the pinned default's ~15s. Nothing here opens a
    # database or a socket; if it did, there would be nothing to configure in
    # this test for it to reach.
    exit_code = main(["--seed", "99991", "--count", "2"])

    assert exit_code == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["null_count"] == 2
    assert payload["signal_count"] == 2
    assert payload["reading"] in {
        TRIAGE_READING_ROBUST_FILTER,
        TRIAGE_READING_LEARNED_SIGNATURE,
        TRIAGE_READING_INDETERMINATE,
    }
    assert payload["population"] == TRIAGE_POPULATION_LABEL


# -- No runpy RuntimeWarning: a subprocess, not an in-process call ------------


def test_module_triage_prints_nothing_to_stderr() -> None:
    # Regression: ``tripwires/__init__.py`` used to import ``tripwires.triage``
    # eagerly, which left "tripwires.triage" in ``sys.modules`` by the time
    # runpy imported it to execute as ``__main__`` -- the exact condition
    # runpy's own RuntimeWarning fires under. Only a real subprocess
    # invocation (as an operator actually runs this command) reproduces it;
    # an in-process call to ``tripwires.triage.main`` never goes through
    # runpy.
    result = subprocess.run(
        [sys.executable, "-m", "tripwires.triage", "--help"],
        capture_output=True,
        text=True,
        env=dict(os.environ),
        check=False,
    )

    assert result.returncode == 0
    assert result.stderr == ""
