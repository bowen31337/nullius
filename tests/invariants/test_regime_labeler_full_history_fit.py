"""System rejects the merge when a regime labeler is configured with a
full-history fit.

app_spec.xml feature 359 — the "System Invariant CI Gates" category's
regime gate — is the merge-time form of a law the spec states twice at
run time, once per member that touches a labeler. Feature 58 (feature
store): *"System labels market regimes using a rolling-window fit only,
which rejects any labeler configured to fit over full history."* Feature
290 (regime): *"System rejects a full-history regime fit, assigning each
stored world to a stratum with the causal rolling-window labeler."*
docs/alpha-engine-prd.md §13 states the law itself, item 6 among the
invariants that *"violating any of these silently invalidates the
system"*: *"Regime labeling is causal. Rolling-window fit only."* — and
§13's preamble names this gate's venue: *"Enforce in CI, not in code
review."* §C1's component table states the failure the law is written
against, in the row named for this very subject: *"Regime labeler —
Rolling-window fit only. Fitting an HMM on full history and then finding
that signal X works in regime 2 is leakage, because regime 2 was labeled
with future data."*

**The subject is the configuration the merge carries, not the labels a
run produces.** A merge ships no dates and no labels — those arrive when
the labeler runs — so the merge-time form of *"a labeler configured with
a full-history fit"* is the **configuration surface** itself, in the
three places a merge carries it. First the **constructor**: the labeler's
own parameter surface, read as data — a fit span offered as a keyword
carrying a finite positive integer default, with no catch-all parameter
that could name an unbounded span the signature does not show. Second
the **composed configuration**: the builder the member registers under
one name, the ``from_env`` construction it calls, and the definition
stamp every persisted record carries — three spellings of one stated
span, which must agree — and the environment configures nothing, because
an environment knob would be a configuration path that ships outside the
merge, invisible to this gate and to review alike. Third the
**behaviour**: every full-history spelling — ``window=None`` above all,
the spelling of an unbounded span, which *"is a full-history fit"* in
feature 58's own words — is refused by the surface it is asked of, in
``FullHistoryFitError`` at construction, and again at fit time when the
span would cover every usable row of the series it is handed (*"a
rolling-window labeler must fit on a trailing window strictly shorter
than the series, never the full history"*).

**The causality the fit span buys is audited directly, because a label
cannot testify about itself.** A stored label is a small integer;
nothing in it says whether the centroid that assigned it was placed with
the future in view, which is why §13 says *"silently"* — the leakage is
invisible in the artefact. The *property* is visible in the labelling: a
trailing-window fit makes the label of date ``t`` a function of the rows
dated ``<= t`` only, so moving the rows after ``t`` cannot move it. The
gate pins that, and pins it non-vacuously: the same audit, run over a
labeler that fits the whole series (the witness class below), moves the
past when the future moves — the finding demonstrated, not merely
described. That is §C1's sentence made executable: a stratum carved with
the signal's own future in view is not a stratum the data drew.

**The census seam is held as the merge's third face.** Feature 290's
census is where the labeler's output becomes the ledger's input — where
a stratum stops being a date's cluster and starts being a count a
promotion gate reads — and it restates the law in its own vocabulary:
:class:`regime.errors.StratumAssignmentError` opening with
``full_history_fit``, raised **before any world is read**, whether the
span arrived as ``None``, as no ``window`` at all, or as a finite number
that spans the world's whole series — *"the full-history fit wearing a
finite number"*, in the census's own words. The gate exercises that seam
from outside the member, the real labeler on the stands side and the
witness on the refusal side, because the census ships in the merge too:
a merge that weakened it would let a full-history-configured labeler
stock the coverage ledger with strata carved by the pool's own future,
and the coverage number that gates a deployment would itself be leakage.

**Why CI, and not only the guards.** Both runtime refusals are checks
the shipped code performs; the configuration surface and the composed
defaults are how a full-history fit would be *created*; and every one of
them — constructor, builder, census — ships in a merge. §13's preamble
says to enforce its invariants in CI, so a merge that weakened any face
— the ``None`` guard demoted to a default, the signature growing an
unbounded fallback, the census reading a span it no longer refuses —
fails this gate before any label is authored anywhere. And the gate
needs no database to do it: the subject is configuration, and
configuration is data (pinned statically below, the same discipline the
ledger and promotion gates apply to their evaluators).

**What this gate is not, asserted as hard as what it is.** It is not the
repository's feature-store suite (``tests/feature-store/
test_regime_labeler.py``) or the regime member's census suites: those
pin each act's own behaviour from inside — the construction and fit-time
refusals, the append-invariance, the census's per-face messages; this
gate reads what a merge carries, from outside it, and adds the face no
writer-side test can promise: a configuration surface that *accepts* a
full-history spelling refuses the merge whatever else it does. It is not
a judgement on the model: the labeler clusters with a seeded k-means,
not the HMM §C1 uses as its example, and the member's own docstring
states why that is not the question — *"the anti-leakage property is a
property of the fit span, not of the model"* — so ``k=7`` and ``k=2``
are not this gate's refusal, and a merge that changed the clustering
would stand so long as the span stayed trailing. It is not a refusal of
finite windows: every causal labeler needs one, and the boundary is
strict and both-sided — a window one row shorter than the series
stands, a window equal to it is refused, because with ``window >= n``
the one fit behind every label spans all the available history. It is
not the service's omit-spelling: ``compute(window=None)`` is the
override seam's way of saying *use the definition's value*, and the fit
that runs is the finite default — the finding is the span of the fit
that runs, never the spelling of the argument that selected it. And it
is not a tag on the labeler's identity: the gate is on the span, not the
object, so a labeler of any shape stating any name is judged by the one
number that constitutes the finding.

**No dialect.** The promotion gate compares timestamps a migration
writes on two engines and the ledger gate reads grants only Postgres can
express; this gate's subject is Python data — a signature, a stated
integer, a seeded fit — and there is no second spelling of it for a
database to disagree about. The one restatement that exists — the fit
span is stamped into every persisted labels record, so an auditor can
read the span off the row — is pinned below exactly as it ships.
"""

from __future__ import annotations

import ast
import datetime as dt
import inspect
import json
import math
import random
import textwrap
from collections.abc import Callable, Sequence
from types import SimpleNamespace
from typing import Any

import pytest
from feature_store import (
    FullHistoryFitError,
    RegimeLabeler,
    RegimeLabelerService,
    RegimeLabels,
    build_regime_labeler_service,
)
from feature_store.bars import DailyBar
from feature_store.regime_labeler import DEFAULT_K, DEFAULT_WINDOW

# The definition stamp is imported from the submodule by its full path on
# purpose: the member's ``__init__`` rebinds the bare name
# ``definition_parameters`` for feature 56's dispersion definition, so the
# package-level spelling would hand this gate a different feature's stamp.
from feature_store.regime_labeler_persistence import (
    decode_labels,
    definition_parameters,
    encode_labels,
)
from regime import (
    DEFAULT_STRATA,
    FULL_HISTORY_FIT_CODE,
    StratumAssignmentError,
    assign_strata,
)

from app.module_loader import registered_components

# ── The law's own spellings, restated as data ────────────────────────────────

#: The one word that opens every full-history refusal the census raises, so
#: the rejection is greppable by the name the feature's own sentence gives
#: it. Restated as data rather than asserted-by-import: a gate that compared
#: the member's constant to itself would agree with the member by
#: construction and pin nothing.
FULL_HISTORY_CODE = "full_history_fit"

#: The version-1 definition's own fit parameters, restated from the shipped
#: definition (``LABELS_DEFINITION`` + ``FEATURE_VERSION`` = "1") rather than
#: imported: the stamp on every record the merge ships, and the one number
#: the finding is about. A merge that moves the definition must move the
#: version with it, and this gate failing is the prompt to re-read both.
VERSION_ONE_K = 3
VERSION_ONE_WINDOW = 63

#: The component name the feature-store member registers its labeler under —
#: the one name a composed application knows the labeler by, restated as data
#: so the gate pins *that* name rather than agreeing with whatever the member
#: registers today.
REGIME_LABELER_COMPONENT = "regime-labeler"

#: The full-history spellings the gate asks every shipped configuration
#: surface to refuse, in the order the law's own words suggest them:
#: ``None`` — the unbounded span, the spelling of "all of history" — and the
#: non-positive spans, which fit on nothing trailing. A surface that accepts
#: any of these is a merge this gate refuses; the per-spelling faces below
#: pin the classes the shipped refusals carry.
FULL_HISTORY_WINDOWS: tuple[tuple[str, Any], ...] = (
    ("window=None — the unbounded span, the spelling of all of history", None),
    ("window=0 — no trailing span to fit on", 0),
    ("window=-63 — a span that reaches before the series begins", -63),
)

# ── The deterministic histories the gate fits over ───────────────────────────

#: The synthetic regime history's shape: 120 dated rows of four features, a
#: calm half then a turbulent half, so the k-means has two regimes to carve
#: and the causality audit below has labels worth moving.
SERIES_LENGTH = 120
ROWS_SEED = 0x5EED1

#: The trailing window the gate fits the synthetic history with — short
#: enough that many positions get labels, long enough that the fit is a real
#: k-means, and strictly shorter than the series (the stands side of the
#: boundary the refusal side pins).
CAUSAL_WINDOW = 30

#: Where the synthetic history's future begins — every row from here on is
#: the "future" the causality audit moves while the past's labels stand.
FUTURE_FROM = SERIES_LENGTH // 2

#: The panel the composed service labels: 170 daily bars of one symbol, calm
#: vol then turbulent, enough history for the vol-of-vol pipeline to make
#: ~90 usable rows and the version-1 window of 63 to label the last of them.
PANEL_DATES = 170
PANEL_SYMBOL = "AAA"
BARS_SEED = 0x5EED2

#: The stored world the census bins: 40 dated rows of two features.
WORLD_ROWS = 40
WORLD_WINDOW = 15
WORLD_SEED = 0x5EED3
GATE_WORLD_ID = "world-gate-1"


def feature_rows(
    count: int = SERIES_LENGTH, *, seed: int = ROWS_SEED
) -> tuple[tuple[float, ...], ...]:
    """A synthetic dated regime history: a calm half, then a turbulent half.

    Four features per row, in date order, every column finite — the usable-row
    contract ``label_features`` states for its argument. The two-half shape
    gives the clustering two genuine regimes to carve, so the stands cases are
    non-vacuous (the labels are not one long flat stratum) and the causality
    audit moves labels that exist. Seeded, so every run of this gate fits the
    same history the merge will.
    """
    rng = random.Random(seed)
    return tuple(
        tuple(rng.gauss(position * 0.01, 0.5 if position < count // 2 else 4.0)
              for _ in range(4))
        for position in range(count)
    )


def future_moved_rows(
    rows: Sequence[Sequence[float]], *, from_position: int = FUTURE_FROM
) -> tuple[tuple[float, ...], ...]:
    """The same history with every row from ``from_position`` on repainted.

    The future, moved: each later row's every feature is scaled and shifted
    far outside the original spread, so any fit whose statistics read those
    rows cannot answer the earlier dates the way it did. A trailing-window
    labeler never reads them for an early date; a full-history fit cannot
    help but read them.
    """
    return tuple(
        row
        if position < from_position
        else tuple(value * 37.0 + 11.0 for value in row)
        for position, row in enumerate(rows)
    )


def daily_bars(
    count: int = PANEL_DATES, *, seed: int = BARS_SEED
) -> tuple[tuple[DailyBar, ...], tuple[dt.date, ...]]:
    """One symbol's daily closes: a calm random walk that turns turbulent.

    The panel shape the composed service is built for — bars, a one-symbol
    universe membership, and the shared date axis — with a volatility shift
    in the middle so the market the labels describe actually changes regime.
    Seeded, so the panel the gate labels is the panel the merge ships code
    for.
    """
    rng = random.Random(seed)
    dates = tuple(dt.date(2025, 1, 1) + dt.timedelta(days=i) for i in range(count))
    calm_until = dt.date(2025, 4, 1)
    price = 100.0
    bars: list[DailyBar] = []
    for date in dates:
        vol = 0.004 if date < calm_until else 0.02
        price *= math.exp(rng.gauss(0.0002, vol))
        bars.append(DailyBar(symbol=PANEL_SYMBOL, date=date, close=price))
    return tuple(bars), dates


def stored_world(
    world_id: str = GATE_WORLD_ID, *, rows: int = WORLD_ROWS, seed: int = WORLD_SEED
) -> SimpleNamespace:
    """One stored world on the census's seam: an identity and a history.

    Carries exactly the two attributes the census duck-reads — ``world_id``
    and ``regime_rows`` — in date order, every column finite, more rows than
    the fit window so the real labeler can bin it and the witness's spanning
    window can be refused for the world it would span.
    """
    rng = random.Random(seed)
    return SimpleNamespace(
        world_id=world_id,
        regime_rows=tuple(
            tuple(rng.gauss(0.0, 0.5 + 0.02 * position) for _ in range(2))
            for position in range(rows)
        ),
    )


# ── The finding's witness ────────────────────────────────────────────────────


class WholeHistoryLabeler:
    """A labeler configured to fit over full history — the finding itself.

    Nothing the shipped surfaces accept can carry the finding: the
    constructor refuses the unbounded spelling, the fit-time guard refuses
    the spanning one, and the census refuses both in its own vocabulary
    before any world is read. So a labeler that fits the whole series
    arrived past them — a backfill, a vendor class, a raw ``SimpleNamespace``
    a caller handed the census — and this class is that hand. Its ``window``
    states ``None`` by default (the unbounded spelling; a finite number can
    be stated instead, which is the full-history fit wearing a finite
    number), and its one act is the leakage §C1 names: every label reads a
    statistic computed over **every** row, so the label of an early date
    moves when a late row does. Two regimes, decided by the whole-series
    mean — the smallest honest model of "regime 2 was labeled with future
    data".
    """

    def __init__(self, *, k: int = 2, window: int | None = None) -> None:
        self._k = k
        self._window = window

    @property
    def k(self) -> int:
        """The label space's size — small and legal, because the span, not
        the cluster count, is the finding."""
        return self._k

    @property
    def window(self) -> int | None:
        """The stated fit span — ``None``, or a finite number that spans the
        series it is refused over."""
        return self._window

    def label_features(
        self, rows: Sequence[Sequence[float]]
    ) -> tuple[int, ...]:
        """Label every row from one fit over the whole series.

        The whole-series mean is the fit; each row is labelled by which side
        of it the row falls. Because the mean reads every row, no label is a
        function of the rows that preceded it — the exact property the
        causality audit below catches, and the shipped labeler's trailing
        window is what guarantees it cannot arise here.
        """
        values = [row[0] for row in rows]
        mean = math.fsum(values) / len(values)
        return tuple(0 if value < mean else 1 for value in values)


# ── The evaluators: the finding as a pure function of stated data ────────────


def full_history_span(window: Any, series_length: int) -> bool:
    """Whether a stated fit span is a full-history fit over ``series_length`` rows.

    The finding the sentence refuses, evaluated over the only two things
    every seam reads: the span a labeler states and the length of the series
    it would fit on. Every spelling the runtime faces refuse folds in here —
    ``None``, the unbounded span; a span that is not a finite positive
    integer (the census refuses those under the same code, because *"a span
    that cannot be read and a span that is unbounded are indistinguishable
    at this seam"* — and a span that is not a number of trailing rows is a
    span nobody can vouch for); and a span that covers every row, which is
    the full-history fit wearing a finite number. The comparison is
    ``>=`` and it is strict both ways: one row short of the series is a
    trailing window, the whole series is not.
    """
    if window is None:
        return True
    if isinstance(window, bool) or not isinstance(window, int) or window < 1:
        return True
    return window >= series_length


def merge_refusal(configure: Callable[..., Any]) -> tuple[str, ...]:
    """The gate itself: the full-history spellings a configuration accepts.

    Asks the merge's own configuration surface — any callable that
    configures a labeler from keyword arguments, which is the shape of both
    shipped surfaces (the labeler's constructor and the service's) — for
    each full-history spelling in turn, and names the spellings it accepted.
    Empty means the merge stands: every full-history spelling was refused by
    the surface it was asked of. Computed by asking, never by fitting, so
    the gate cannot author a label while judging the configuration that
    would produce one.

    A spelling counts as refused when asking for it raises; the
    per-spelling faces below pin the exact classes the shipped refusals
    carry, which is what keeps this aggregate's breadth anchored rather
    than excused — the gate does not care which vocabulary refuses the
    span, only that some refusal does.
    """
    accepted: list[str] = []
    for spelling, window in FULL_HISTORY_WINDOWS:
        try:
            configure(window=window)
        except Exception:  # noqa: BLE001, S112 - the finding is the
            # *acceptance*: the gate does not care which vocabulary refuses
            # the span, only that some refusal does, and the per-spelling
            # faces below pin the classes the shipped refusals carry.
            continue
        accepted.append(spelling)
    return tuple(accepted)


# ── The gate reads the configuration the merge carries ───────────────────────


class TestTheGateReadsTheConfigurationTheMergeCarries:
    """The gate judges the signature, the stamp and the seam a merge ships,
    as data, without opening anything."""

    def test_the_gate_reads_the_labeler_the_member_exports(self) -> None:
        # The gate reads the labeler the composition loads — the class the
        # member exports is the class the module's own computation module
        # defines, and its refusal is the vocabulary the member chose for a
        # caller bug: a ValueError, because asking for a full-history fit is
        # a configuration error, never a runtime condition to retry. A gate
        # that judged a re-typed copy of the class could agree with itself
        # and pass anything; this one fails the moment the owner moves.
        import feature_store.regime_labeler as labeler_module

        assert RegimeLabeler is labeler_module.RegimeLabeler
        assert FullHistoryFitError is labeler_module.FullHistoryFitError
        assert issubclass(FullHistoryFitError, ValueError)

    def test_the_signature_the_merge_ships_offers_no_unbounded_span(self) -> None:
        # The configuration surface read as data. ``window`` is a keyword —
        # a caller must name the span it is asking for — and its default is
        # a finite positive integer, restated here as the version-1
        # definition's own value: the constructor's fallback is a trailing
        # window, never an unbounded one, and a signature whose ``window``
        # defaulted to ``None`` would make the full-history fit the merge's
        # own out-of-the-box configuration. No catch-all ``**kwargs`` either:
        # a VAR_KEYWORD parameter could carry a spelling of "all of history"
        # the signature does not show and no reader could audit.
        parameters = inspect.signature(RegimeLabeler.__init__).parameters
        window = parameters["window"]
        assert window.kind is inspect.Parameter.KEYWORD_ONLY
        default = window.default
        assert not isinstance(default, bool)
        assert isinstance(default, int)
        assert default >= 1
        assert default == DEFAULT_WINDOW == VERSION_ONE_WINDOW
        assert parameters["k"].default == DEFAULT_K == VERSION_ONE_K
        assert all(
            parameter.kind is not inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        )

    def test_the_stamps_the_merge_carries_state_one_span(self) -> None:
        # The definition stamp — the sentence every persisted labels record
        # carries — states the law in words and the fit parameters as
        # numbers, and the three spellings of the span the merge ships (the
        # constructor's default, the computation module's constant, the
        # stamp on the record) are one number. A merge that moved one
        # without the others would ship records claiming a definition the
        # code no longer states, which is precisely the silent drift this
        # category exists to catch at merge time.
        stamp = definition_parameters()
        assert "trailing window only" in str(stamp["labels"])
        assert stamp["window"] == DEFAULT_WINDOW == VERSION_ONE_WINDOW
        assert stamp["k"] == DEFAULT_K == VERSION_ONE_K

    def test_the_composition_registers_the_labeler_under_one_name(self) -> None:
        # The composed configuration's identity: the member registers its
        # labeler builder under one name — restated as data here — and the
        # builder it registers is the module-level function the member
        # exports. This is the seam a composed application reads the
        # labeler through, so it is the seam whose weakening (a second
        # registration, a renamed builder resolved to nothing) would leave
        # the pool counting strata against a labeler nobody composed.
        # The loader imports member packages under scan aliases
        # (``_nullius_scanned_<pkg>``), so the registered builder is
        # structurally the exported function but never the same module
        # object a direct ``import feature_store`` yields — the member's
        # own registration suite states the rule: verify name and
        # behaviour, never identity across the two module worlds.
        components = {
            component.name: component.builder
            for component in registered_components()
        }
        builder = components[REGIME_LABELER_COMPONENT]
        assert builder.__name__ == build_regime_labeler_service.__name__
        assert builder.__module__.endswith("feature_store")
        # And the behavioural half of the rule: whatever world the
        # registered builder was imported in, the service it builds
        # labels the panel exactly as ``from_env`` does — the fields are
        # plain data (a tuple of labels, two ints), so they compare
        # across the worlds the objects themselves cannot.
        bars, dates = daily_bars()
        composed = builder().compute(bars, (PANEL_SYMBOL,), dates)
        from_env = RegimeLabelerService.from_env().compute(
            bars, (PANEL_SYMBOL,), dates
        )
        assert composed.labels == from_env.labels
        assert (composed.k, composed.window) == (DEFAULT_K, DEFAULT_WINDOW)

    def test_the_environment_configures_nothing_the_merge_does_not_carry(self) -> None:
        # The third configuration path, closed statically. The service's
        # own docstring states the design — *"No environment is read: the
        # cluster count and the fit window are definition parameters
        # carried by ``feature_version``"* — and this pin holds the merge to
        # it: an environment knob would be a way to configure a full-history
        # fit that ships outside the merge entirely, invisible to this gate
        # and to review. ``from_env`` is the construction the registered
        # builder calls, so the pin covers the composed path, not a test
        # convenience.
        # Dedented because a classmethod's source arrives at class-body
        # indentation, and the parse is of the method as it ships.
        tree = ast.parse(
            textwrap.dedent(inspect.getsource(RegimeLabelerService.from_env))
        )
        environment_names = [
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and node.attr in {"environ", "getenv", "getenvb"}
        ]
        assert environment_names == []

    def test_the_gate_judges_the_configuration_without_opening_a_database(self) -> None:
        # A merge gate refuses the change before it ships; the subject here
        # is configuration, and configuration is data. The static check the
        # ledger and promotion gates apply to their evaluators, pinned for
        # both of this gate's: neither touches anything that could open,
        # drive or settle a connection — a gate that had to run something to
        # judge it would be an audit after the fact.
        for evaluator in (full_history_span, merge_refusal):
            tree = ast.parse(inspect.getsource(evaluator))
            database_names = [
                node.attr
                for node in ast.walk(tree)
                if isinstance(node, ast.Attribute)
                and node.attr
                in {
                    "connect",
                    "cursor",
                    "execute",
                    "executescript",
                    "commit",
                    "rollback",
                }
            ]
            assert database_names == []


# ── A merge whose labeler fits a trailing window stands ──────────────────────


class TestAMergeWhoseLabelerFitsATrailingWindowStands:
    """The shipped labeler, exercised once over a deterministic history,
    configures a finite trailing window, labels causally, and bins the pool
    through the census — the merge stands by construction."""

    def test_the_default_configuration_is_a_finite_trailing_window_that_labels(
        self,
    ) -> None:
        # The stands case stated end-to-end: the constructor's own defaults
        # configure a finite trailing window, and that labeler labels the
        # synthetic history — no label before the first full window (positions
        # ``0 .. window-2`` carry ``None``, the honest spelling of "not yet
        # enough history to judge"), an integer cluster from ``window-1`` on,
        # and more than one cluster actually used, so the read is pinned
        # non-vacuous: the fit described the market, it did not name one
        # stratum and stop.
        labeler = RegimeLabeler()
        assert isinstance(labeler.window, int)
        assert labeler.window >= 1
        assert labeler.k >= 2
        labels = labeler.label_features(feature_rows())
        assert all(label is None for label in labels[: labeler.window - 1])
        assert all(isinstance(label, int) for label in labels[labeler.window - 1 :])
        assert len({label for label in labels if label is not None}) >= 2

    def test_a_window_one_row_shorter_than_the_series_stands(self) -> None:
        # The boundary's stands side, and it is load-bearing: the refusal is
        # ``window >= n``, so ``window == n - 1`` is a legal trailing window —
        # the last date's fit sees every row but the one the series has not
        # reached yet. A gate that refused this would be refusing every short
        # history, and a labeler that accepted one row more would be fitting
        # the full history; the boundary is one row wide and both sides of it
        # are pinned (the other side below).
        rows = feature_rows()
        labeler = RegimeLabeler(window=len(rows) - 1)
        labels = labeler.label_features(rows)
        assert labels[-1] is not None

    def test_the_composed_service_labels_a_panel_under_the_stamped_definition(
        self,
    ) -> None:
        # The composed configuration, exercised once the way the factory
        # composes it: the registered builder and the ``from_env``
        # construction it calls both label the panel — a real market history
        # through the vol pipeline — under the stamped definition's span, and
        # the two spellings of the composition agree, because there is one
        # configuration and no environment to disagree with it.
        bars, dates = daily_bars()
        composed = build_regime_labeler_service().compute(
            bars, (PANEL_SYMBOL,), dates
        )
        from_env = RegimeLabelerService.from_env().compute(
            bars, (PANEL_SYMBOL,), dates
        )
        assert composed == from_env
        assert composed.n_labeled > 0
        assert composed.k == definition_parameters()["k"]
        assert composed.window == definition_parameters()["window"]

    def test_the_labels_before_a_position_do_not_move_when_the_rows_after_it_do(
        self,
    ) -> None:
        # The causality audit — the property the whole law exists for, and
        # the one thing a stored label cannot testify about. Baseline labels
        # over the history; then the future is repainted far outside its
        # original spread and the labelling runs again. The labels of every
        # position before the perturbation are bit-for-bit identical,
        # because the trailing window that produced each of them ended at
        # that position and never read a row after it — the seeded fit is a
        # pure function of the window, and the window did not change. That
        # is "regime 2 was labeled with future data" refused in the
        # negative: no label here knows any future.
        rows = feature_rows()
        moved = future_moved_rows(rows)
        assert moved != rows
        labeler = RegimeLabeler(k=DEFAULT_K, window=CAUSAL_WINDOW)
        baseline = labeler.label_features(rows)
        relabelled = labeler.label_features(moved)
        assert relabelled[:FUTURE_FROM] == baseline[:FUTURE_FROM]
        assert relabelled[FUTURE_FROM:] != baseline[FUTURE_FROM:]

    def test_the_same_audit_over_a_full_history_fit_moves_the_past(self) -> None:
        # The audit's non-vacuity, and the finding demonstrated rather than
        # described. The witness fits the whole series — its one statistic
        # reads every row — so repainting the future moves the boundary the
        # past is labelled against, and the labels before the perturbation
        # change. The two tests together say the audit discriminates: it
        # passes exactly the fit that cannot see the future and fails
        # exactly the fit that must.
        rows = feature_rows()
        witness = WholeHistoryLabeler()
        baseline = witness.label_features(rows)
        relabelled = witness.label_features(future_moved_rows(rows))
        assert relabelled[:FUTURE_FROM] != baseline[:FUTURE_FROM]

    def test_the_census_bins_a_pool_through_the_real_labeler(self) -> None:
        # The stands side of the seam: the real labeler — finite trailing
        # window, stated ``k`` — handed across the census with a stored
        # world, and the world is binned into a stratum of the default
        # vocabulary. The merge's two halves compose: the labeler feature 58
        # ships and the census feature 290 ships agree on one
        # configuration, which is the merge standing by construction.
        world = stored_world()
        assignments = assign_strata(
            [world], RegimeLabeler(k=DEFAULT_K, window=WORLD_WINDOW)
        )
        assert len(assignments) == 1
        assert assignments[0].world_id == world.world_id
        assert assignments[0].stratum in DEFAULT_STRATA


# ── A merge that configures a full-history fit is refused ────────────────────


class TestAMergeThatConfiguresAFullHistoryFitIsRefused:
    """Every full-history spelling is refused by every surface the merge
    ships — and a surface that accepts one is the refusal, whatever else
    that merge does."""

    def test_the_unbounded_span_is_refused_at_construction(self) -> None:
        # The canonical spelling: ``window=None``, "all of history". The
        # refusal is the member's own class and names the finding in the
        # member's own words — an unbounded span *is* a full-history fit —
        # so the operator reads the leakage off the exception, not a type
        # error about an int they never sent.
        with pytest.raises(FullHistoryFitError) as excinfo:
            RegimeLabeler(window=None)
        message = str(excinfo.value)
        assert "unbounded" in message
        assert "full-history" in message

    @pytest.mark.parametrize("window", [0, -63])
    def test_the_non_positive_spans_are_refused_at_construction(
        self, window: int
    ) -> None:
        # The degenerate spellings: a window that fits on nothing trailing.
        # These are the same guard's other edge — the span must be a finite
        # positive integer — and the same class refuses them, because a
        # labeler asked to fit on no trailing rows is being asked for a fit
        # whose span is not a span.
        with pytest.raises(FullHistoryFitError) as excinfo:
            RegimeLabeler(window=window)
        assert ">= 1" in str(excinfo.value)

    @pytest.mark.parametrize("window", [float("inf"), "full history", True, 2.0])
    def test_a_span_that_is_not_a_number_of_rows_cannot_be_configured(
        self, window: Any
    ) -> None:
        # The type-level spellings: an infinity, a sentence, a boolean, a
        # float. The surface refuses each with a ``TypeError`` — these are
        # caller bugs, not configurations — and the pin matters because a
        # surface that coerced any of them (``int(window)``, a truthiness
        # check, ``None or len(rows)``) would have built a door to the
        # unbounded span out of a type it never validated. The gate's
        # aggregate does not count these spellings; the constructor's own
        # totality does, and this is it.
        with pytest.raises(TypeError):
            RegimeLabeler(window=window)

    def test_every_shipped_configuration_surface_refuses_every_spelling(self) -> None:
        # The gate's own happy path, stated as the gate states it: both
        # configuration surfaces the merge ships — the labeler's constructor
        # and the service's, which is the constructor's configuration
        # carried one seam up — refuse every full-history spelling. Empty
        # findings on both, so the merge stands.
        assert merge_refusal(lambda **kwargs: RegimeLabeler(**kwargs)) == ()
        assert merge_refusal(lambda **kwargs: RegimeLabelerService(**kwargs)) == ()

    def test_a_surface_that_accepts_a_spelling_is_the_refusal(self) -> None:
        # The load-bearing regression case. The witness accepts every
        # full-history spelling — its constructor never refuses — and the
        # gate names each spelling it accepted, deterministically, in the
        # order the law's own words suggest them. A future edit to the
        # labeler that weakened its guard (the ``None`` check demoted to a
        # default, the positivity check dropped) turns the test above
        # non-empty right here, at merge time, before any label exists.
        refusal = merge_refusal(lambda **kwargs: WholeHistoryLabeler(**kwargs))
        assert refusal == tuple(spelling for spelling, _ in FULL_HISTORY_WINDOWS)

    def test_a_window_that_spans_the_series_is_refused_at_fit_time(self) -> None:
        # The degeneracy face: a finite, positive, legal-looking window that
        # covers every usable row of the series it is handed. With
        # ``window >= n`` the one fit behind every label spans all the
        # available history — indistinguishable from the full-history fit —
        # and the refusal names both numbers so the operator sees the span
        # against the series, not just the word "refused".
        rows = feature_rows()
        for window in (len(rows), len(rows) + 5):
            with pytest.raises(FullHistoryFitError) as excinfo:
                RegimeLabeler(window=window).label_features(rows)
            message = str(excinfo.value)
            assert str(window) in message
            assert str(len(rows)) in message

    def test_the_service_delegates_the_same_refusal(self) -> None:
        # One seam up, the same law: the service cannot be asked for a
        # full-history fit either. A window that spans every usable row the
        # panel's pipeline will produce is refused by the labeler the
        # service delegates to — the service adds orchestration, never a
        # way around the guard.
        bars, dates = daily_bars()
        with pytest.raises(FullHistoryFitError):
            RegimeLabelerService().compute(
                bars, (PANEL_SYMBOL,), dates, window=10**6
            )

    def test_the_census_refuses_the_unbounded_span_before_any_world_is_read(
        self,
    ) -> None:
        # The seam's configuration face, in the regime member's own
        # vocabulary: a labeler whose stated span is ``None`` is refused
        # with the greppable code — restated as data above, pinned against
        # the member's constant here — and the refusal fires before any
        # world is read, pinned by handing the census a pool that cannot be
        # iterated at all: the error that surfaces is the span's, not the
        # pool's, so a full-history configuration is refused without the
        # census having to read, label or write anything.
        assert FULL_HISTORY_FIT_CODE == FULL_HISTORY_CODE

        class WorldsThatCannotBeRead:
            def __iter__(self) -> Any:
                raise AssertionError("the census read a world")

        with pytest.raises(StratumAssignmentError) as excinfo:
            assign_strata(WorldsThatCannotBeRead(), WholeHistoryLabeler())
        assert str(excinfo.value).startswith(FULL_HISTORY_CODE)

    def test_the_census_refuses_a_finite_window_spanning_the_world(self) -> None:
        # The seam's degeneracy face: the witness stating a finite window
        # that spans the stored world's whole series — the full-history fit
        # wearing a finite number. The witness states ``k=3`` here so the
        # vocabulary check (which runs before any world) passes against the
        # default three names and the refusal that surfaces is the span's,
        # not the vocabulary's — a different face of a different sentence.
        # The refusal names the world and both numbers (the span and the
        # row count), so the operator reads the finding off the world it is
        # about.
        world = stored_world()
        with pytest.raises(StratumAssignmentError) as excinfo:
            assign_strata(
                [world], WholeHistoryLabeler(k=DEFAULT_K, window=WORLD_ROWS)
            )
        message = str(excinfo.value)
        assert message.startswith(FULL_HISTORY_CODE)
        assert world.world_id in message
        assert f"window={WORLD_ROWS}" in message
        assert str(WORLD_ROWS) in message

    def test_the_census_refusal_is_the_regime_members_own_vocabulary(self) -> None:
        # The error-vocabulary law every member seam restates: the census
        # refuses in ``StratumAssignmentError`` — the regime member's own
        # class, an ``Exception`` sibling — never in the labeler's
        # ``FullHistoryFitError``, which a caller of this member never
        # imported and must not have to. The merge carries both classes;
        # this pins that the seam between them translates.
        with pytest.raises(StratumAssignmentError) as excinfo:
            assign_strata([stored_world()], WholeHistoryLabeler())
        assert not isinstance(excinfo.value, FullHistoryFitError)


# ── The finding is exactly the full-history span and nothing else ────────────


class TestTheFindingIsExactlyTheFullHistorySpanAndNothingElse:
    """The gate refuses exactly the sentence's finding: a stated span that
    is unbounded or covers the whole series — never a finite trailing
    window, a cluster count, a model, or an omit-spelling."""

    def test_a_finite_trailing_window_is_not_the_finding(self) -> None:
        # The ordinary shape of a causal labeler, stated at the evaluator:
        # a finite positive window over a series longer than it. Nothing
        # about this span contradicts §13 item 6 — the label of every date
        # rests on a trailing window ending at that date — and a gate that
        # refused it would be refusing every labeler the law permits,
        # which is the only kind the law permits.
        assert not full_history_span(VERSION_ONE_WINDOW, SERIES_LENGTH)
        assert not full_history_span(SERIES_LENGTH - 1, SERIES_LENGTH)
        assert not full_history_span(1, 2)

    def test_the_boundary_is_strict_the_last_row_makes_the_difference(self) -> None:
        # The comparison is ``>=`` and the finding is any span that covers
        # the series, not a margin: one row short of the series is a
        # trailing window, equal to it is the full history, longer than it
        # is the full history of a series that never reached the window's
        # end. A gate that forgave the equal case would be forgiving the
        # one-row-shorter case's exact complement — there is no daylight
        # between "every row" and "every row".
        n = SERIES_LENGTH
        assert full_history_span(n, n)
        assert full_history_span(n + 5, n)
        assert not full_history_span(n - 1, n)

    def test_the_unbounded_and_unreadable_spelling_are_the_finding(self) -> None:
        # Every spelling folds to the finding, matching the census's own
        # consolidation: ``None`` (unbounded), a non-positive span, a
        # boolean (``True`` is an ``int`` in Python, but a flag is not a
        # number of rows), a float infinity, a sentence. At the seam where
        # a labeler's output becomes a ledger's input, a span that cannot
        # be read and a span that is unbounded are indistinguishable, and
        # the one thing the seam must not do is guess — so the gate, like
        # the census, refuses them all.
        assert full_history_span(None, 10**9)
        assert full_history_span(0, 10)
        assert full_history_span(-63, 10)
        assert full_history_span(True, 10)
        assert full_history_span(float("inf"), 10)
        assert full_history_span("full history", 10)

    def test_the_model_and_its_cluster_count_are_not_the_subject(self) -> None:
        # The scope is the span, exactly as the sentence's is. A labeler
        # carving two clusters or seven, over a finite trailing window, is
        # configured causally whatever it clusters with — the member's own
        # docstring states why: *"the anti-leakage property is a property
        # of the fit span, not of the model"*, which is why a k-means
        # stands in for the PRD's HMM without weakening the law. A gate
        # that refused ``k=7`` would be refusing a sentence that is not
        # this one's, and the operator would go hunting leakage that is
        # not there.
        for k in (2, 7):
            labeler = RegimeLabeler(k=k, window=CAUSAL_WINDOW)
            assert labeler.k == k
            labels = labeler.label_features(feature_rows())
            assert all(
                isinstance(label, int) and 0 <= label < k
                for label in labels[CAUSAL_WINDOW - 1 :]
            )

    def test_the_services_omit_spelling_lands_on_the_finite_default(self) -> None:
        # The one ``None`` the shipped surface legitimately accepts, and the
        # distinction is the gate's own subject: at the service's override
        # seam, ``window=None`` is the omit-spelling — *use the definition's
        # value* — and the fit that runs is the finite default, pinned here
        # by the labels being the default's labels. The finding is the span
        # of the fit that runs, never the spelling of the argument that
        # selected it; the constructor's ``None`` and the override's name
        # the same token for opposite reasons, and only one of them is a
        # configuration.
        bars, dates = daily_bars()
        service = RegimeLabelerService.from_env()
        assert service.compute(bars, (PANEL_SYMBOL,), dates, window=None) == (
            service.compute(bars, (PANEL_SYMBOL,), dates)
        )

    def test_a_stored_record_states_the_span_it_was_fit_with(self) -> None:
        # The restatement the merge ships: every persisted labels record
        # carries its fit span in the payload, so an auditor can read the
        # span off the row the same way the promotion gate reads its two
        # timestamps. The envelope states the finite window the labels were
        # fit under, and the decoder reconstructs the record exactly —
        # which is what makes the stamp checkable rather than a matter of
        # trust.
        rows = feature_rows()
        window = 10
        labels = RegimeLabeler(window=window).label_features(rows)
        record = RegimeLabels(
            dates=tuple(
                dt.date(2025, 1, 1) + dt.timedelta(days=position)
                for position in range(len(rows))
            ),
            labels=labels,
            k=DEFAULT_K,
            window=window,
            n_labeled=sum(1 for label in labels if label is not None),
        )
        payload = encode_labels(record, top_n=1)
        assert json.loads(payload)["window"] == window
        assert decode_labels(payload) == record
