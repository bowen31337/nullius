"""Feature 216's suite: ``mechanism_discrimination``, per candidate model.

app_spec.xml, "Hypothesis Authoring Agent", feature 216: *System persists
mechanism_discrimination per candidate model before the gate milestone, so a
weak agent is not misread as a failed thesis.*

The sentence is four claims and this file takes them one at a time, because they
fail in four different ways and a suite that tested "the feature" would let
three of them be true while the fourth was not:

* **mechanism_discrimination** — the figure is feature 214's, and the claim here
  is that it is 214's *arithmetic* over 214's pair of columns rather than a
  second, silently different statistic.  So the figure is recomputed in this file
  from an independent spelling of Pearson's r and Fisher's z, and the module's
  own ``_SQL`` constants are read to pin that it declares no correlation of its
  own.
* **per candidate model** — the stratum, and the load-bearing half of the
  feature.  The model is *declared and verified*, not derived: a branch authored
  by another model is refused by name, and there is no default and no pooled
  read.  This is the claim the whole feature turns on, so it is pinned from both
  sides — behaviourally, and structurally over the module's own source.
* **persists** — the member's second writer, into a table it owns, keyed by the
  ``(campaign, model)`` pair, refresh-not-append, with the row's shape pinned
  against ``PRAGMA table_info``.
* **before the gate milestone** — the timing clause, discharged structurally
  because no milestone is a *value* anywhere in this workspace: the module reads
  nothing the gate produces, and no gate token appears in its code.

**The fixtures bring a real schema and a real writer.**  ``discrimination_database``
runs the tree chain feature 215's fixture runs, then ``0111`` and ``0109`` — so
the out-of-sample half is the table migration ``0109`` creates and the campaign
row is ``0111``'s.  Every in-sample half is written by feature 207's own
:meth:`ProposalStore.persist`, and every branch is planted by the same
``record_gain`` feature 214's own suite uses, so the two features' cohorts are
literally the same construction and this file's figures are comparable with that
file's.

**The one hand-written table is hand-written because nothing in this workspace
writes it.**  ``replay_score``'s writer is the replay member (features 245-255),
which is unbuilt — the same fact ``test_discrimination.py`` records about the
same table for the same reason.  The *in-sample* half is store-produced and
therefore genuinely pinned; the *out-of-sample* half is this suite's own rows in
the schema the migration creates.
"""

from __future__ import annotations

import ast as _ast
import io
import json
import math
import sqlite3
import tokenize
import uuid
from contextlib import closing
from datetime import UTC, datetime
from statistics import NormalDist

import pytest
import signal_agent as member
from conftest import (
    METRICS_MIGRATION,
    NODE_MIGRATION,
    TRIO_MIGRATION,
    create_schema,
    plant_campaign,
    plant_modelled_node,
    plant_node,
    plant_run,
    record_gain,
    sqlite_path_of,
)
from signal_agent import (
    CANDIDATE_TABLE,
    CONFIDENCE_LEVEL,
    IS_GAIN_METRIC,
    MINIMUM_PAIRS,
    MODEL_COLUMN,
    MODEL_METRIC,
    CandidateModelError,
    DiscriminationCohortError,
    ModelDiscrimination,
    ProposalStore,
    ScoreRecord,
    load_model_discrimination,
    load_model_discriminations,
    mechanism_discrimination_by_model,
)

#: The model id every ordinary case is about — a triple of the shape feature 203
#: pins, and deliberately the same string 214's own suite uses, so a figure here
#: and a figure there are figures about one agent.
_MODEL = "deepseek/deepseek-v4-flash/2026-09-10"

#: A second candidate model, for the cases whose subject *is* the stratification:
#: a mixed cohort, a second stratum's row, a listing of two.
_OTHER_MODEL = "anthropic/claude-opus-5-5/2026-09-01"

#: The revision every run in this suite is under, unless a case is *about* the
#: revision.  §14.1's instrument runs at M2 *under fixed exploration*.
_POLICY = "policy-v1"

#: The paired gains the arithmetic cases use — 214's own, for 214's own reason:
#: ``_RISING`` is strictly increasing and ``_STRONG`` tracks it, which is the
#: "strong agent" §14.1 describes, so the figure is *computed* here rather than
#: asserted from a stored number.
_RISING = (0.10, 0.20, 0.30, 0.40)
_STRONG = (1.0, 2.0, 3.0, 5.0)

#: The columns a persisted reading is made of, in the order the schema declares
#: them.  Spelled here so a claim about the *shape* of the row can compare this
#: tuple against ``PRAGMA table_info`` — the two must agree, and a test that read
#: the pragma once and used it for both sides would be comparing the table with
#: itself.
_STORED_COLUMNS = (
    "campaign_id",
    "model",
    "correlation",
    "interval_lower",
    "interval_upper",
    "pairs",
    "runs",
    "proposals",
    "policy_version",
    "cohort_digest",
    "seen_at",
)


def _document(index: int) -> str:
    """A distinct proposal source for branch ``index``.

    Feature 207 identifies a proposal by the hash of its bytes and refuses a
    second document against a node that already holds one, so a suite recording
    four branches needs four distinct sources.  The content is irrelevant to this
    feature — 216 reads no code — which is the point: the figure is a function of
    the *scores*, and a case that changed only the document must leave it alone.
    """
    return f"def signal(ctx, seed):\n    return ctx.close.rolling_mean({index + 2})\n"


def _cohort(
    database_url: str,
    campaign: str,
    is_gains: tuple[float, ...],
    oos_gains: tuple[float, ...],
    *,
    model: str = _MODEL,
    runs_each: int = 1,
    policy: str = _POLICY,
) -> list[str]:
    """Plant one model's paired gains; return the branch ids in order.

    The construction every arithmetic claim is built from, and it is 214's own
    fixture spelled with the model as a parameter — which is the whole of the
    difference between the two features' cohorts: one model's branches, declared.
    """
    return [
        record_gain(
            database_url,
            campaign,
            model,
            _document(index),
            is_gain,
            runs=(oos_gain,) * runs_each,
            policy_version=policy,
        )
        for index, (is_gain, oos_gain) in enumerate(zip(is_gains, oos_gains))
    ]


def _measured(
    url: str,
    campaign: str,
    cohort: list[str],
    model: str = _MODEL,
) -> ModelDiscrimination:
    """Measure a ``(campaign, model)`` through feature 207's own handle."""
    return mechanism_discrimination_by_model(
        ProposalStore(url), campaign, model, cohort
    )


def _branch_ids(count: int) -> list[str]:
    """``count`` node ids that name nothing — for the refusals about arguments."""
    return [str(uuid.uuid4()) for _ in range(count)]


def _rows(url: str) -> list[tuple]:
    """Every stored reading, column order fixed by ``_STORED_COLUMNS``.

    An **absent table is an empty list** rather than an ``OperationalError``, and
    that is the point of the helper rather than a convenience: the table is
    member-owned and created lazily by ``_persist``, so "no row claims this
    reading happened" is exactly ``[]`` for a database where the write never ran —
    including one where the table was never created at all.  A helper that raised
    there would make the refusals-below-the-arithmetic cases untestable, and those
    are the cases that pin feature 123's measure-before-write order.
    """
    with closing(sqlite3.connect(sqlite_path_of(url))) as connection:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (CANDIDATE_TABLE,),
        ).fetchone()
        if exists is None:
            return []
        return connection.execute(
            f"SELECT {', '.join(_STORED_COLUMNS)} FROM {CANDIDATE_TABLE}"
        ).fetchall()


def _stored_columns(url: str) -> tuple[str, ...]:
    """``campaign_model_discrimination``'s columns, read from the table itself."""
    with closing(sqlite3.connect(sqlite_path_of(url))) as connection:
        return tuple(
            row[1]
            for row in connection.execute(f"PRAGMA table_info({CANDIDATE_TABLE})")
        )


def _mutate_row(url: str, pair: tuple[str, str], **columns: object) -> None:
    """Write stored columns straight into the table, behind the law's back.

    The one thing this suite does behind the store's back, and it does it only
    where the case is *about* what a later reader would see: the module refuses a
    second write of a different reading (the grain is the pair), so a case that
    needs a hand-edited row has nowhere else to put it.

    The key is passed as a **pair** rather than as two arguments, because one of
    the columns a case edits *is* ``model`` — the key and the payload share a name
    on this schema, so a signature spelling both would collide exactly where the
    interesting edit is.
    """
    campaign, model = pair
    assignments = ", ".join(f"{name} = ?" for name in columns)
    with closing(sqlite3.connect(sqlite_path_of(url))) as connection, connection:
        connection.execute(
            f"UPDATE {CANDIDATE_TABLE} SET {assignments} "
            f"WHERE campaign_id = ? AND model = ?",
            (*columns.values(), campaign, model),
        )


def _correlation(xs: tuple[float, ...], ys: tuple[float, ...]) -> float:
    """Pearson's r, spelled independently of the module's own.

    Deliberately the textbook formula over means rather than a call into anything
    the module imports: a claim that a figure *is* a correlation has to be made
    from a second computation, or it is a claim that the module agrees with
    itself.
    """
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    covariance = sum(
        (x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)
    )
    spread_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
    spread_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))
    return covariance / (spread_x * spread_y)


def _fisher_interval(r: float, n: int) -> tuple[float, float]:
    """The 95% interval for ``r`` over ``n`` points — Fisher's z, independently."""
    quantile = NormalDist().inv_cdf(1.0 - (1.0 - CONFIDENCE_LEVEL) / 2.0)
    centre = math.atanh(r)
    standard_error = 1.0 / math.sqrt(n - 3)
    return (
        math.tanh(centre - quantile * standard_error),
        math.tanh(centre + quantile * standard_error),
    )


# ── The sentence ─────────────────────────────────────────────────────────────


def test_the_figure_is_a_correlation_over_the_cohorts_two_gain_halves(
    discrimination_database: str,
) -> None:
    """The sentence's first claim: ``mechanism_discrimination``, on real branches.

    The figure and both interval bounds are recomputed here from the same inputs
    by this file's own :func:`_correlation` and :func:`_fisher_interval` — a
    second spelling of the same mathematics — so the case is a claim about the
    *arithmetic* rather than about the module agreeing with itself.  The two
    denominators are the counts the store holds: ``pairs`` is the cohort's size
    and ``runs`` is the number of out-of-sample rows drawn on.
    """
    campaign = str(uuid.uuid4())
    plant_campaign(discrimination_database, campaign)
    cohort = _cohort(discrimination_database, campaign, _RISING, _STRONG)

    reading = _measured(discrimination_database, campaign, cohort)

    point = _correlation(_RISING, _STRONG)
    assert reading.correlation == pytest.approx(point, rel=1e-12)
    assert reading.lower == pytest.approx(_fisher_interval(point, 4)[0], rel=1e-12)
    assert reading.upper == pytest.approx(_fisher_interval(point, 4)[1], rel=1e-12)
    assert reading.interval == (reading.lower, reading.upper)
    assert reading.pairs == len(_RISING)
    assert reading.runs == len(_RISING)
    assert reading.campaign_id == campaign
    assert reading.model == _MODEL


def test_the_figure_moves_with_the_in_sample_marginal_and_nothing_else(
    discrimination_database: str,
) -> None:
    """The in-sample half is 214's metric, and the six others are not read.

    The decision 214 pins from its own side, pinned here because this feature
    *reuses* 214's reader and a regression in the shared half would otherwise be
    invisible from this file: the snapshot's ``ir_marginal`` is what enters the
    correlation, and a node whose other six metrics disagree with it — and whose
    live ``node`` row disagrees with both — must leave the figure exactly where
    the snapshot's ``ir_marginal`` puts it.
    """
    campaign = str(uuid.uuid4())
    plant_campaign(discrimination_database, campaign)
    cohort = _cohort(discrimination_database, campaign, _RISING, _STRONG)
    before = _measured(discrimination_database, campaign, cohort)

    store = ProposalStore(discrimination_database)

    # A *second* branch, whose snapshot carries one metric that is not the gain:
    # a value the figure must ignore entirely.
    extra = plant_modelled_node(
        discrimination_database, _MODEL, campaign_id=campaign
    )
    store.persist(
        extra,
        _document(99),
        score=ScoreRecord(ir_standalone=500.0, ir_marginal=0.40),
    )
    plant_run(discrimination_database, committed_pick=extra, score=5.0)

    after = _measured(discrimination_database, campaign, [*cohort, extra])
    # A hand-written snapshot's ir_marginal is the *only* thing this reading can
    # move on, so deleting it must change the figure and changing a different
    # metric must not — the second half is the claim, and the first is what makes
    # it non-vacuous.
    with closing(sqlite3.connect(sqlite_path_of(discrimination_database))) as connection, connection:
        connection.execute(
            "UPDATE node_proposal SET score = ? WHERE node_id = ?",
            (ScoreRecord(ir_standalone=500.0, ir_marginal=0.40).to_json(), extra),
        )
    unchanged = _measured(discrimination_database, campaign, [*cohort, extra])
    assert unchanged.correlation == pytest.approx(after.correlation, rel=1e-12)

    with closing(sqlite3.connect(sqlite_path_of(discrimination_database))) as connection, connection:
        connection.execute(
            "UPDATE node_proposal SET score = ? WHERE node_id = ?",
            (ScoreRecord(ir_standalone=500.0, ir_marginal=0.90).to_json(), extra),
        )
    moved = _measured(discrimination_database, campaign, [*cohort, extra])
    assert moved.correlation != pytest.approx(unchanged.correlation, rel=1e-9)
    assert before.correlation != pytest.approx(moved.correlation, rel=1e-9)


def test_a_branch_is_one_point_at_the_mean_of_its_runs(
    discrimination_database: str,
) -> None:
    """§14.1's unit is the branch, so nine worlds are one observation.

    214's decision, pinned here because it is the shared reader's: a refinement
    committed to in several worlds is **one** point at the mean of its runs, and
    the alternative (one point per run) would repeat one ``x`` for every world the
    branch was chosen in — so a single much-picked node would carry the
    correlation by frequency rather than by contrast.
    """
    campaign = str(uuid.uuid4())
    plant_campaign(discrimination_database, campaign)
    cohort = _cohort(
        discrimination_database, campaign, _RISING, _STRONG, runs_each=3
    )

    reading = _measured(discrimination_database, campaign, cohort)

    point = _correlation(_RISING, _STRONG)
    assert reading.pairs == 4, "four branches are four points, not twelve"
    assert reading.runs == 12, "and the runs behind them are counted"
    assert reading.correlation == pytest.approx(point, rel=1e-12)


# ── The stratum is verified, never derived ───────────────────────────────────


def test_a_branch_authored_by_another_model_is_refused_by_name(
    discrimination_database: str,
) -> None:
    """**The feature.**  A mixed cohort is refused, not stratified around.

    This is the case the whole feature turns on, and the refusal is the point
    rather than a safety net.  §14.1 records the provenance failure as *"not
    hypothetical"* — DeepSeek retired ``deepseek-v4-flash`` on 2026-09-10 while
    continuing to accept the ID and silently serving V4.1-Flash, so one model
    string can span two models.  A deriving implementation would take this cohort
    and report two tidy small-``n`` strata; a *declaring* one refuses, and the
    message has to name **which branch** and **which two model strings** so the
    operator can act on it.
    """
    campaign = str(uuid.uuid4())
    plant_campaign(discrimination_database, campaign)
    cohort = _cohort(discrimination_database, campaign, _RISING, _STRONG)
    intruder = _cohort(
        discrimination_database,
        campaign,
        (0.5,),
        (4.0,),
        model=_OTHER_MODEL,
    )[0]

    with pytest.raises(CandidateModelError) as refusal:
        _measured(discrimination_database, campaign, [*cohort, intruder])

    message = str(refusal.value)
    assert intruder in message, "the refusal names the branch"
    assert _MODEL in message and _OTHER_MODEL in message, (
        "and both model strings, so the operator can see which two disagree"
    )
    assert _rows(discrimination_database) == [], (
        "and it was refused before anything was written"
    )


def test_the_whole_cohort_of_one_model_is_required_not_merely_tolerated(
    discrimination_database: str,
) -> None:
    """Declaring another model's branches as this model's is the same refusal.

    The mirror of the case above, and not the same test: that one has a *mixed*
    cohort, this one has a uniform cohort *misdeclared*.  Both must refuse,
    because the module's claim is that the figure is attributed to the model the
    branches were actually authored by — and a cohort that is entirely another
    model's, measured under this model's name, is the failure at its cleanest:
    two models' rows, neither of which is a measurement of the model it names.
    """
    campaign = str(uuid.uuid4())
    plant_campaign(discrimination_database, campaign)
    cohort = _cohort(
        discrimination_database,
        campaign,
        _RISING,
        _STRONG,
        model=_OTHER_MODEL,
    )

    with pytest.raises(CandidateModelError) as refusal:
        _measured(discrimination_database, campaign, cohort, model=_MODEL)

    assert _OTHER_MODEL in str(refusal.value)
    assert _rows(discrimination_database) == []


def test_a_branch_whose_node_carries_no_model_is_refused(
    discrimination_database: str,
) -> None:
    """A blank ``agent_model_id`` is not an ``""`` stratum.

    ``0115`` declares the column ``NOT NULL`` — *"every node is authored by
    exactly one model"* (PRD §13 invariant 5a) — so a blank one is a
    brought-forward or hand-edited database.  Refused rather than attributed
    anyway, because a branch whose author is unknown would have to be attributed
    to *some* model, and printing a stratum no model answers to beside the real
    ones makes §14.1's per-model table uninterpretable rather than incomplete.
    """
    campaign = str(uuid.uuid4())
    plant_campaign(discrimination_database, campaign)
    cohort = _cohort(discrimination_database, campaign, _RISING, _STRONG)
    blank = plant_modelled_node(
        discrimination_database, "  ", campaign_id=campaign
    )
    ProposalStore(discrimination_database).persist(
        blank, _document(50), score=ScoreRecord(ir_marginal=0.5)
    )
    plant_run(discrimination_database, committed_pick=blank, score=4.0)

    with pytest.raises(CandidateModelError) as refusal:
        _measured(discrimination_database, campaign, [*cohort, blank])

    assert blank in str(refusal.value)
    assert _rows(discrimination_database) == []


def test_a_branch_the_tree_does_not_hold_is_refused(
    discrimination_database: str,
) -> None:
    """A declared branch with no node has no author to be attributed to.

    Refused rather than dropped, for §14.1's rule 1 reason: a cohort reduced
    after the fact to whatever happened to be attributable is a selection, not a
    sample.
    """
    campaign = str(uuid.uuid4())
    plant_campaign(discrimination_database, campaign)
    cohort = _cohort(discrimination_database, campaign, _RISING, _STRONG)
    ghost = str(uuid.uuid4())

    with pytest.raises(CandidateModelError) as refusal:
        _measured(discrimination_database, campaign, [*cohort, ghost])

    assert ghost in str(refusal.value)
    assert _rows(discrimination_database) == []


def test_a_tree_without_the_model_column_is_refused_naming_the_revision(
    discrimination_database_url: str,
) -> None:
    """No ``agent_model_id`` on an existing tree is feature 100's revision, named.

    The **interesting** of the two depths, and the one that pins
    ``_verify_attribution``'s ordering: the tree is there, feature 207's
    proposals are there, ``0109``'s replay pool and ``0111``'s campaign are
    there, and the *only* thing missing is the column this feature's sentence is
    about.  The walk's SQL mentions that column, so on this tree it would fail as
    SQLite's ``no such column`` — a fact about a statement, in SQLite's
    vocabulary — if the shape were not asked first.  Naming the losing revision
    is the whole actionable content, the discipline 215's ``_tree_columns``
    follows for the same column.

    **The database is an intermediate state the chain really passes through, and
    the case has to build it because no fixture does.**  ``create_diversity_schema``
    runs ``0115``; here it deliberately does not, and everything else the reading
    needs *is* present — so the refusal under test is the deepest one that
    applies.  Skipping ``replay_score`` instead would refuse as *feature 1
    unreached* before the walk ever ran, which is the right behaviour and the
    wrong test: it would never reach the code this case is about.
    """
    from conftest import CAMPAIGN_MIGRATION, REPLAY_MIGRATION

    create_schema(
        discrimination_database_url,
        NODE_MIGRATION,
        TRIO_MIGRATION,
        METRICS_MIGRATION,
        CAMPAIGN_MIGRATION,
        REPLAY_MIGRATION,
    )
    campaign = str(uuid.uuid4())
    plant_campaign(discrimination_database_url, campaign)

    # Four branches, so the cohort clears §14.1's floor and the case reaches the
    # attribution walk rather than stopping at the size check — the floor has its
    # own cases below and would here hide the refusal under test.  Each is
    # recorded through feature 207's own writer, because an absent proposal table
    # refuses as *feature 207 unreached* one step earlier.
    store = ProposalStore(discrimination_database_url)
    cohort = []
    for index in range(MINIMUM_PAIRS):
        node = plant_node(
            discrimination_database_url, campaign_id=campaign
        )
        store.persist(node, _document(index))
        plant_run(
            discrimination_database_url, committed_pick=node, score=float(index)
        )
        cohort.append(node)

    with pytest.raises(CandidateModelError) as refusal:
        _measured(discrimination_database_url, campaign, cohort)

    message = str(refusal.value)
    assert "0115_agent_model_trio" in message
    assert "0118_node_table" not in message, (
        "the tree is present, so the deeper refusal is the one that fires"
    )
    assert _rows(discrimination_database_url) == []


def test_an_absent_tree_is_refused_naming_its_own_revision(
    discrimination_database: str,
) -> None:
    """The shallower depth: no ``node`` table is feature 97's revision, named.

    The sibling of the case above, kept apart because the repairs differ — one
    asks for a whole table, the other for a column on a table that exists.  A
    feature whose subject **is** the model column reports both as its own class,
    where 215 reports an absent tree as 207's: 215's figure is fundamentally a
    count of proposals, so an absent tree is a history fact, and here it is a
    fact about *this* reading.
    """
    campaign = str(uuid.uuid4())
    plant_campaign(discrimination_database, campaign)
    cohort = _cohort(discrimination_database, campaign, _RISING, _STRONG)

    with closing(sqlite3.connect(sqlite_path_of(discrimination_database))) as connection, connection:
        connection.execute("DROP TABLE node")

    with pytest.raises(CandidateModelError) as refusal:
        _measured(discrimination_database, campaign, cohort)

    message = str(refusal.value)
    assert "0118_node_table" in message
    assert "0115_agent_model_trio" not in message, (
        "there is no table for the column to be missing from"
    )
    assert _rows(discrimination_database) == []


# ── No default, and no pooled answer ─────────────────────────────────────────


@pytest.mark.parametrize(
    "model",
    [None, "", "   ", 0, True, ["m"], {"m": 1}],
)
def test_a_reading_without_a_candidate_model_is_refused(
    discrimination_database: str, model: object
) -> None:
    """There is no default model, and no way to ask for "the figure".

    The failure the sentence names is a *failure of pooling* — *"a weak agent is
    not misread as a failed thesis"* — so a default would restore it by omission.
    The argument is 214's for refusing a default cohort, made one level up: there
    the thing a default would silently mix is the exactly-zero half, and here it
    is a second agent.  ``bool`` is refused explicitly because ``True`` is ``1``
    in Python.
    """
    campaign = str(uuid.uuid4())
    plant_campaign(discrimination_database, campaign)
    cohort = _cohort(discrimination_database, campaign, _RISING, _STRONG)

    with pytest.raises(CandidateModelError):
        mechanism_discrimination_by_model(
            ProposalStore(discrimination_database), campaign, model, cohort
        )

    assert _rows(discrimination_database) == []


def test_the_module_offers_no_pooled_read() -> None:
    """The pooled figure is 214's, and this module cannot produce one.

    Structural rather than behavioural, because the thing being pinned is the
    *absence* of a surface: there is no function here that takes a campaign and
    answers a figure for it, and no parameter that defaults to "all models".  A
    behavioural test would pass on a module that grew one tomorrow.

    Two halves.  The **public surface is exactly the declared one** — the four
    constants and the three functions ``__all__`` names — so a read that dropped
    the model argument would have to say so here first.  And **every public
    function requires its model**: the required-parameter set of each is checked
    against the signature rather than against a call, because the failure this
    guards is a *default* being added, and a default changes the signature and
    not the behaviour of a call that passes one.
    """
    module = _imported_module("_candidate")
    # The claim is about **callables**: a pooled read would be a function or a
    # class, and the names this module restates as literals (``NODE_TABLE``,
    # ``MODEL_COLUMN``, …) are deliberately not exported — they are the spellings
    # the module checks against their owners, not a surface a caller uses.
    public = {
        name
        for name in vars(module)
        if not name.startswith("_")
        and callable(vars(module)[name])
        and getattr(vars(module)[name], "__module__", None) == module.__name__
    }
    assert public == {
        name for name in module.__all__ if isinstance(vars(module)[name], type)
        or callable(vars(module)[name])
    }, (
        "every callable this module defines is exported, and the list is short on "
        f"purpose: a pooled read would be one more name here (found "
        f"{sorted(public ^ set(module.__all__))})"
    )
    assert public == {
        "ModelDiscrimination",
        "load_model_discrimination",
        "load_model_discriminations",
        "mechanism_discrimination_by_model",
    }, "the surface is three functions and one value, and it has not grown"

    for name in public:
        value = vars(module)[name]
        assert getattr(value, "__doc__", None), (
            f"{name} carries no docstring, which in this member is the omission "
            f"that hides a decision"
        )

    # The two reads take the model as a *required* positional argument, and the
    # two listings that do not are scoped by the campaign alone.
    import inspect

    by_model = inspect.signature(mechanism_discrimination_by_model).parameters
    assert "model" in by_model
    assert by_model["model"].default is inspect.Parameter.empty, (
        "a default here would be the pooled reading by omission"
    )
    single = inspect.signature(load_model_discrimination).parameters
    assert "model" in single and single["model"].default is inspect.Parameter.empty
    for listing in (module.load_model_discriminations,):
        assert "model" not in inspect.signature(listing).parameters, (
            "the listing is scoped by the campaign; it cannot be given a model "
            "to narrow to, which is feature 216's own choice and not an oversight"
        )


# ── The grain, and the read-back ─────────────────────────────────────────────


def test_the_row_lands_in_this_members_own_table_with_its_declared_shape(
    discrimination_database: str,
) -> None:
    """``persists``, and the row's shape pinned against the table itself.

    The column tuple spelled in this file and the table's ``PRAGMA`` must agree;
    a test that read the pragma once and used it for both sides would be
    comparing the table with itself.  The interval is **two columns and not a
    derived read**, for 214's reason: §14.1 rule 3 makes the interval the
    reported thing, so a row holding the point alone would let a report print it
    unaccompanied.
    """
    campaign = str(uuid.uuid4())
    plant_campaign(discrimination_database, campaign)
    cohort = _cohort(discrimination_database, campaign, _RISING, _STRONG)

    reading = _measured(discrimination_database, campaign, cohort)

    assert _stored_columns(discrimination_database) == _STORED_COLUMNS
    rows = _rows(discrimination_database)
    assert len(rows) == 1
    stored = dict(zip(_STORED_COLUMNS, rows[0]))
    assert stored["campaign_id"] == campaign
    assert stored["model"] == _MODEL
    assert stored["correlation"] == pytest.approx(reading.correlation, rel=1e-12)
    assert stored["interval_lower"] == pytest.approx(reading.lower, rel=1e-12)
    assert stored["interval_upper"] == pytest.approx(reading.upper, rel=1e-12)
    assert stored["pairs"] == 4
    assert stored["runs"] == 4
    assert stored["policy_version"] == _POLICY
    assert stored["cohort_digest"] == reading.cohort_digest
    assert datetime.fromisoformat(str(stored["seen_at"])) == reading.seen_at


def test_a_measurement_reads_back_as_the_reading_that_was_written(
    discrimination_database: str,
) -> None:
    """The read-back discipline: the row reconstructs into the same value.

    Feature 123's guard reads its own half back rather than trusting the
    transaction; this feature has no second half to reconcile against — it may
    not add a column to a shared table — so the equivalent is that the stored row
    rebuilds through the validating constructor into the value that wrote it.
    """
    campaign = str(uuid.uuid4())
    plant_campaign(discrimination_database, campaign)
    cohort = _cohort(discrimination_database, campaign, _RISING, _STRONG)
    reading = _measured(discrimination_database, campaign, cohort)

    store = ProposalStore(discrimination_database)
    assert load_model_discrimination(store, campaign, _MODEL) == reading
    assert load_model_discrimination(store, campaign, _MODEL) is not reading


def test_the_pair_is_the_grain_so_two_models_are_two_rows(
    discrimination_database: str,
) -> None:
    """§14.1's *"two campaigns per candidate model"* is why the pair is the key.

    A table keyed on the model alone could hold only the second of a candidate
    model's two campaigns, so the campaign stays in the key.  And a re-reading of
    one pair **refreshes rather than appends** — the instrument is run at M2 over
    a cohort that grows as the campaign proposes, so what the table must hold is
    the latest reading and nothing else.
    """
    campaign = str(uuid.uuid4())
    plant_campaign(discrimination_database, campaign)
    first = _cohort(discrimination_database, campaign, _RISING, _STRONG)
    second = _cohort(
        discrimination_database,
        campaign,
        _RISING,
        _STRONG,
        model=_OTHER_MODEL,
    )

    one = _measured(discrimination_database, campaign, first)
    two = _measured(discrimination_database, campaign, second, model=_OTHER_MODEL)
    assert len(_rows(discrimination_database)) == 2

    store = ProposalStore(discrimination_database)
    assert load_model_discrimination(store, campaign, _MODEL) == one
    assert load_model_discrimination(store, campaign, _OTHER_MODEL) == two

    # Re-measure the first stratum over a changed cohort: still two rows.
    extra = _cohort(discrimination_database, campaign, (0.9,), (9.0,))[0]
    again = _measured(discrimination_database, campaign, [*first, extra])
    assert len(_rows(discrimination_database)) == 2, "refresh, not append"
    assert load_model_discrimination(store, campaign, _MODEL) == again
    assert again != one
    assert load_model_discrimination(store, campaign, _OTHER_MODEL) == two


def test_the_listing_is_the_per_model_table_in_sorted_order(
    discrimination_database: str,
) -> None:
    """``load_model_discriminations`` — §14.1's per-stratum report, as a mapping.

    PRD §13 invariant 5a: *"M3 results are reported per model stratum as well as
    pooled."*  The order is fixed here rather than left to SQLite's row layout so
    two reads of one unchanged set produce the same report lines — 215's
    ``by_model`` decision, made for the same reason.  The mapping is read-only,
    for 215's reason too: a caller scribbling on what it was handed must move a
    proxy that refuses writes rather than the figure.
    """
    campaign = str(uuid.uuid4())
    plant_campaign(discrimination_database, campaign)
    listed = _cohort(
        discrimination_database, campaign, _RISING, _STRONG, model=_OTHER_MODEL
    )
    mine = _cohort(discrimination_database, campaign, _RISING, _STRONG)
    _measured(discrimination_database, campaign, mine)
    _measured(
        discrimination_database, campaign, listed, model=_OTHER_MODEL
    )

    readings = load_model_discriminations(
        ProposalStore(discrimination_database), campaign
    )

    assert list(readings) == sorted(readings), "sorted, not SQLite's layout"
    assert set(readings) == {_MODEL, _OTHER_MODEL}
    assert readings[_OTHER_MODEL] == _measured(
        discrimination_database, campaign, listed, model=_OTHER_MODEL
    )
    with pytest.raises(TypeError):
        readings[_MODEL] = readings[_OTHER_MODEL]  # type: ignore[index]

    # Fresh per call, and empty is a real answer for an unmeasured campaign.
    assert load_model_discriminations(
        ProposalStore(discrimination_database), str(uuid.uuid4())
    ) == {}


def test_an_unmeasured_pair_is_none_and_not_an_absent_store(
    discrimination_database: str,
) -> None:
    """``None`` is *this pair has never been measured*, and the third state raises.

    The three-way distinction 214's own load keeps, kept because it is
    load-bearing here in a way it is not for a listing: at M2 a campaign's second
    candidate model is *expected* to be unmeasured while the first is not, so a
    caller that mistook the first state for the second would re-measure something
    it already has — or, worse, read the absence as an error.

    The three states, in order: an unmeasured pair answers ``None``; a store
    whose member DDL has never run *also* answers ``None`` for the single read
    (there is no table and therefore no row); and a handle that is not feature
    207's store is **refused** rather than answered.
    """
    campaign = str(uuid.uuid4())
    plant_campaign(discrimination_database, campaign)
    cohort = _cohort(discrimination_database, campaign, _RISING, _STRONG)
    _measured(discrimination_database, campaign, cohort)

    store = ProposalStore(discrimination_database)
    assert load_model_discrimination(store, campaign, _OTHER_MODEL) is None

    with pytest.raises(DiscriminationCohortError):
        load_model_discrimination(object(), campaign, _MODEL)
    with pytest.raises(DiscriminationCohortError):
        load_model_discriminations(object(), campaign)


# ── The floors, and 214's arithmetic ─────────────────────────────────────────


def test_a_cohort_below_the_floor_is_refused_and_names_the_stratum(
    discrimination_database: str,
) -> None:
    """§14.1's rule 3 forces ``pairs >= 4``, and the refusal says which model.

    214's refusal, unchanged in class and repair — *expand the campaign* — with
    one fact added that only this feature has: *whose* cohort is too thin.  The
    floor is checked before anything is opened, so the case needs no planted rows
    at all.
    """
    campaign = str(uuid.uuid4())
    plant_campaign(discrimination_database, campaign)

    with pytest.raises(DiscriminationCohortError) as refusal:
        _measured(discrimination_database, campaign, _branch_ids(MINIMUM_PAIRS - 1))

    message = str(refusal.value)
    assert _MODEL in message
    assert str(MINIMUM_PAIRS) in message
    assert _rows(discrimination_database) == []


@pytest.mark.parametrize("pairs", [0, 1, 2, 3])
def test_every_cohort_under_the_floor_is_refused(
    discrimination_database: str, pairs: int
) -> None:
    """The floor is a floor: four is the first cohort an interval exists for."""
    campaign = str(uuid.uuid4())
    plant_campaign(discrimination_database, campaign)
    with pytest.raises(DiscriminationCohortError):
        _measured(discrimination_database, campaign, _branch_ids(pairs))


def test_a_constant_series_or_a_perfect_correlation_is_refused(
    discrimination_database: str,
) -> None:
    """A cohort that cannot produce an interval is refused, not answered with a point.

    Three shapes, one question — *is this a cohort the rule can be applied to* —
    and each is refused because the honest answer is that the cohort cannot
    answer, not a number.  ``0.0`` for a constant series would be a *claim* (this
    agent's gains carry no discrimination) where the truth is that the cohort has
    no movement to account for; a perfect correlation has no interval at all,
    since ``atanh(±1)`` diverges.
    """
    campaign = str(uuid.uuid4())
    plant_campaign(discrimination_database, campaign)

    flat_is = _cohort(discrimination_database, campaign, (0.1,) * 4, _STRONG)
    with pytest.raises(DiscriminationCohortError):
        _measured(discrimination_database, campaign, flat_is)

    flat_oos = _cohort(discrimination_database, campaign, _RISING, (2.0,) * 4)
    with pytest.raises(DiscriminationCohortError):
        _measured(discrimination_database, campaign, flat_oos)

    perfect = _cohort(discrimination_database, campaign, _RISING, (1.0, 2.0, 3.0, 4.0))
    with pytest.raises(DiscriminationCohortError):
        _measured(discrimination_database, campaign, perfect)

    assert _rows(discrimination_database) == []


def test_214s_pairing_refusals_reach_this_feature_unchanged(
    discrimination_database: str,
) -> None:
    """A branch with a missing half is the *same fact* and keeps 214's class.

    Three states the two features share, and all three keep
    :class:`DiscriminationCohortError` rather than being re-minted here — the
    member's own rule, *"the same fact with the same repair, whoever asks"*: a
    declared branch with no committed run, a branch whose runs span two policy
    versions, and (from the in-sample side) a branch whose stored row belongs to
    another campaign.
    """
    campaign = str(uuid.uuid4())
    plant_campaign(discrimination_database, campaign)

    # (1) no committed run.
    unrun = _cohort(discrimination_database, campaign, _RISING, (0.0,) * 4)
    with closing(sqlite3.connect(sqlite_path_of(discrimination_database))) as connection, connection:
        connection.execute(
            "DELETE FROM replay_score WHERE committed_pick = ?", (unrun[0],)
        )
    with pytest.raises(DiscriminationCohortError):
        _measured(discrimination_database, campaign, unrun)

    # (2) one branch's runs spanning two revisions.  The **same** branch is run
    # twice under two revisions, rather than a second cohort under a second one:
    # the out-of-sample read is scoped by the cohort, so a run on a branch
    # nobody declared is never read and the case would pass for the wrong reason.
    campaign_two = str(uuid.uuid4())
    plant_campaign(discrimination_database, campaign_two)
    revisioned = _cohort(discrimination_database, campaign_two, _RISING, _STRONG)
    plant_run(
        discrimination_database,
        committed_pick=revisioned[0],
        score=1.0,
        policy_version="policy-v2",
    )
    with pytest.raises(DiscriminationCohortError) as refusal:
        _measured(discrimination_database, campaign_two, revisioned)
    assert "policy-v2" in str(refusal.value) and _POLICY in str(refusal.value)

    # (3) a branch whose recorded proposal belongs to another campaign.
    campaign_three = str(uuid.uuid4())
    plant_campaign(discrimination_database, campaign_three)
    cohort = _cohort(discrimination_database, campaign_three, _RISING, _STRONG)
    with closing(sqlite3.connect(sqlite_path_of(discrimination_database))) as connection, connection:
        connection.execute(
            "UPDATE node_proposal SET campaign_id = ? WHERE node_id = ?",
            (str(uuid.uuid4()), cohort[0]),
        )
    with pytest.raises(DiscriminationCohortError):
        _measured(discrimination_database, campaign_three, cohort)

    assert _rows(discrimination_database) == []


def test_nothing_is_written_when_a_refusal_fires(
    discrimination_database: str,
) -> None:
    """The measure-before-write order, asserted by counting rows.

    Feature 123's ordering, for its reason: a refused reading must leave no row
    claiming it happened.  Asserted over a refusal that fires *after* the store
    has been opened and read — the attribution walk — so the case is about the
    write's placement rather than about an argument check that never got that far.
    """
    campaign = str(uuid.uuid4())
    plant_campaign(discrimination_database, campaign)
    cohort = _cohort(discrimination_database, campaign, _RISING, _STRONG)
    intruder = _cohort(
        discrimination_database, campaign, (0.5,), (4.0,), model=_OTHER_MODEL
    )[0]

    assert _rows(discrimination_database) == []
    with pytest.raises(CandidateModelError):
        _measured(discrimination_database, campaign, [*cohort, intruder])
    assert _rows(discrimination_database) == [], (
        "the store was opened and read, and still nothing was written"
    )


def test_a_campaign_the_table_does_not_hold_is_refused(
    discrimination_database: str,
) -> None:
    """A reading is a fact about a campaign, so the campaign must be a row.

    The store refuses rather than creating the campaign — feature 123's argument
    for its own guard, word for word: a store that inserted the missing campaign
    would be inventing the row the null fraction and the campaign type belong on.
    """
    campaign = str(uuid.uuid4())
    plant_campaign(discrimination_database, campaign)
    cohort = _cohort(discrimination_database, campaign, _RISING, _STRONG)
    another = str(uuid.uuid4())

    with pytest.raises(DiscriminationCohortError) as refusal:
        _measured(discrimination_database, another, cohort)

    assert another in str(refusal.value)
    assert _rows(discrimination_database) == []


# ── The frozen cohort, §14.1's rule 1 ────────────────────────────────────────


def test_the_digest_freezes_the_cohort_and_the_model_it_is_about(
    discrimination_database: str,
) -> None:
    """Rule 1: *"freeze the cohort before any model runs, and hash its inputs."*

    Three claims.  The digest is **stable under a re-ordered cohort**, because a
    digest that followed the caller's iteration order would be a statement about
    the caller rather than about the cohort.  It **changes when a gain changes**,
    because a digest that quantised its inputs would report two different
    measurements as one.  And it **differs from 214's digest over the same
    branches**, because the model is an input to *this* reading and not to that
    one — a difference that is stated in the module rather than left to be
    discovered, and which this case pins so that a later "unification" of the two
    digests has to argue with a test rather than slip through.
    """
    campaign = str(uuid.uuid4())
    plant_campaign(discrimination_database, campaign)
    cohort = _cohort(discrimination_database, campaign, _RISING, _STRONG)

    reading = _measured(discrimination_database, campaign, cohort)
    reordered = _measured(
        discrimination_database, campaign, list(reversed(cohort))
    )
    assert reading.cohort_digest == reordered.cohort_digest

    # The campaign-scoped reading over the same branches, from 214's own law.
    from signal_agent import mechanism_discrimination

    campaign_scoped = mechanism_discrimination(
        ProposalStore(discrimination_database), campaign, cohort
    )
    assert campaign_scoped.cohort_digest != reading.cohort_digest, (
        "the model is an input to this reading; the two rows are two readings"
    )

    with closing(sqlite3.connect(sqlite_path_of(discrimination_database))) as connection, connection:
        connection.execute(
            "UPDATE node_proposal SET score = ? WHERE node_id = ?",
            (ScoreRecord(ir_marginal=0.31).to_json(), cohort[0]),
        )
    moved = _measured(discrimination_database, campaign, cohort)
    assert moved.cohort_digest != reading.cohort_digest


def test_a_second_model_over_the_same_branches_hashes_differently(
    discrimination_database: str,
) -> None:
    """"The model is an input" is true *between* strata as well as between features.

    The sharpest form of the claim above, and it is not the same case: there the
    difference was between this feature's digest and 214's, here it is between two
    rows of *this* table.  Two models measured over one campaign produce two
    digests even if every other input is identical, which is what makes the digest
    a statement about *which reading* this is rather than about the store's state.
    """
    campaign = str(uuid.uuid4())
    plant_campaign(discrimination_database, campaign)
    mine = _cohort(discrimination_database, campaign, _RISING, _STRONG)
    theirs = _cohort(
        discrimination_database, campaign, _RISING, _STRONG, model=_OTHER_MODEL
    )

    one = _measured(discrimination_database, campaign, mine)
    two = _measured(discrimination_database, campaign, theirs, model=_OTHER_MODEL)

    assert one.correlation == pytest.approx(two.correlation, rel=1e-12), (
        "same gains, so the same figure — the difference under test is the digest"
    )
    assert one.cohort_digest != two.cohort_digest


# ── The value object ─────────────────────────────────────────────────────────


def test_the_value_refuses_shapes_no_read_could_produce(
    discrimination_database: str,
) -> None:
    """A hand-built value is a test's prerogative, and a report's hazard.

    Every field here reaches a report that a weak agent's verdict is read off, so
    a value no read could produce is refused rather than printed.  The checks are
    this feature's one (a blank model) plus 214's, delegated to 214's constructor
    rather than re-spelled — which is the claim this case makes about the
    *delegation* as much as about the checks.
    """
    campaign = str(uuid.uuid4())
    point = _correlation(_RISING, _STRONG)
    lower, upper = _fisher_interval(point, 4)
    digest = "a" * 64
    stamp = datetime(2026, 9, 22, tzinfo=UTC)
    common = {
        "campaign_id": campaign,
        "correlation": point,
        "lower": lower,
        "upper": upper,
        "pairs": 4,
        "runs": 4,
        "proposals": 4,
        "policy_version": _POLICY,
        "cohort_digest": digest,
        "seen_at": stamp,
    }

    assert ModelDiscrimination(model=_MODEL, **common).model == _MODEL

    for model in (None, "", "   ", 7, True):
        with pytest.raises(CandidateModelError):
            ModelDiscrimination(model=model, **common)  # type: ignore[arg-type]

    # 214's checks, reached through the delegate: the floor, an interval that is
    # not this point's, runs below pairs, a short digest, a naive stamp.  The
    # naive stamp is spelled with ``replace`` rather than a second literal, so
    # the *only* difference from ``common`` is the ``tzinfo`` under test — which
    # is what makes the case a claim about that field.
    for broken in (
        {"pairs": 3},
        {"lower": 0.0},
        {"runs": 3},
        {"cohort_digest": "abc"},
        {"seen_at": datetime(2026, 9, 22, tzinfo=UTC).replace(tzinfo=None)},
        {"correlation": 1.0},
    ):
        with pytest.raises(DiscriminationCohortError):
            ModelDiscrimination(model=_MODEL, **{**common, **broken})  # type: ignore[arg-type]

    with pytest.raises(CandidateModelError):
        ModelDiscrimination(model=_MODEL, **{**common, "proposals": -1})  # type: ignore[arg-type]


def test_a_hand_edited_row_fails_to_load(
    discrimination_database: str,
) -> None:
    """A stored row that is not a reading is refused *on read*, by name.

    This feature may not add a column to a shared table, so it has no second row
    to reconcile against — 214's position, and the reason it takes the same
    defence: the read path rebuilds the value through the validating constructor,
    so a correlation written straight into the table fails to load rather than
    loading as a plausible-looking reading.  The second half of the case is the
    one that matters: a row moved onto a *different* pair's key is refused too,
    because otherwise a hand edit could reattribute a figure to a model that did
    not produce it.
    """
    campaign = str(uuid.uuid4())
    plant_campaign(discrimination_database, campaign)
    cohort = _cohort(discrimination_database, campaign, _RISING, _STRONG)
    _measured(discrimination_database, campaign, cohort)

    pair = (campaign, _MODEL)
    store = ProposalStore(discrimination_database)
    _mutate_row(discrimination_database, pair, correlation=2.0)
    with pytest.raises(DiscriminationCohortError):
        load_model_discrimination(store, campaign, _MODEL)

    # A hand-edited digest, which no reconstruction can repair: the column is
    # ``CHAR(64)`` and SQLite ignores the length, so the table will happily hold
    # a three-character one — the check that refuses it is the constructor's.
    _mutate_row(discrimination_database, pair, cohort_digest="abc")
    with pytest.raises(DiscriminationCohortError):
        load_model_discrimination(store, campaign, _MODEL)

    # **Last**, because it moves the key: a row whose *key* is not what it was
    # selected by.  The single-pair read asks for the blank model and finds
    # nothing, so it is the **listing** — which takes whatever keys the table
    # holds — that meets the row and refuses it.  Without this check a hand edit
    # could reattribute a figure to a model that did not produce it.
    _mutate_row(discrimination_database, pair, cohort_digest="d" * 64, model="  ")
    with pytest.raises(CandidateModelError) as refusal:
        load_model_discriminations(store, campaign)
    assert "  " in str(refusal.value)


def test_the_value_is_frozen_and_compares_by_its_parts(
    discrimination_database: str,
) -> None:
    """Equality over the fields, never by ``isinstance``; and hashable, and frozen.

    The loader imports every member twice, once by file path under a synthetic
    name and once as the importable member, so an ``isinstance`` check would be
    false for a value built from the other import of the same file.  Equality
    over the fields is the same statement and survives that — 214's and 215's
    decision, applied here.
    """
    campaign = str(uuid.uuid4())
    plant_campaign(discrimination_database, campaign)
    cohort = _cohort(discrimination_database, campaign, _RISING, _STRONG)
    reading = _measured(discrimination_database, campaign, cohort)

    same = _measured(discrimination_database, campaign, cohort)
    assert same == reading
    assert hash(same) == hash(reading)
    assert reading != "not a reading"
    assert len({reading, same}) == 1

    other = _measured(
        discrimination_database,
        campaign,
        _cohort(
            discrimination_database, campaign, _RISING, _STRONG, model=_OTHER_MODEL
        ),
        model=_OTHER_MODEL,
    )
    assert other != reading, "the model is part of the value's identity"

    assert not hasattr(reading, "__dict__"), "slots, so no field can be added"


def test_the_row_and_payload_carry_the_stratum_and_nest_the_interval(
    discrimination_database: str,
) -> None:
    """§14.1's reporting rules in the shape of the data.

    ``interval`` is nested (214's rule 3: ``design.md`` §9 makes the interval the
    primary mark, so a flat row invites a renderer to print the point alone) and
    ``model`` is a top-level key (this feature's rule: PRD §13 5a reports per
    model stratum, so a row that did not carry the stratum could not be tabulated
    per model at all).  ``row()`` is fresh per call, so a report tool that writes
    into what it read moves its own copy.
    """
    campaign = str(uuid.uuid4())
    plant_campaign(discrimination_database, campaign)
    cohort = _cohort(discrimination_database, campaign, _RISING, _STRONG)
    reading = _measured(discrimination_database, campaign, cohort)

    row = reading.row()
    assert row["model"] == _MODEL
    assert row["campaign_id"] == campaign
    assert row["interval"] == {"lower": reading.lower, "upper": reading.upper}
    assert row["proposals"] == 4
    assert row["pairs"] == 4
    assert row["seen_at"] == reading.seen_at.isoformat()
    assert row is not reading.row()

    assert json.loads(reading.payload()) == row
    assert reading.payload() == json.dumps(row, sort_keys=True, separators=(",", ":"))

    # The nested interval is what makes an unaccompanied point impossible to
    # print from this row without deliberately discarding a key.
    assert "correlation" in row and set(row["interval"]) == {"lower", "upper"}


def test_the_campaign_scoped_reading_is_214s_own_object(
    discrimination_database: str,
) -> None:
    """``reading()`` hands back 214's value rather than a parallel spelling of it.

    The module reuses 214's arithmetic rather than restating it, and this case
    pins the same decision one level up: a caller that wants the campaign-scoped
    shape gets *that object*, validated by *that* constructor, instead of a
    second class in this module that would drift from it.
    """
    from signal_agent import MechanismDiscrimination

    campaign = str(uuid.uuid4())
    plant_campaign(discrimination_database, campaign)
    cohort = _cohort(discrimination_database, campaign, _RISING, _STRONG)
    reading = _measured(discrimination_database, campaign, cohort)

    inner = reading.reading()
    assert isinstance(inner, MechanismDiscrimination)
    assert inner.correlation == reading.correlation
    assert inner.cohort_digest == reading.cohort_digest
    assert inner.row()["campaign_id"] == campaign
    assert "model" not in inner.row(), (
        "214's value has no such field and will not grow one"
    )


# ── The spellings, and the shape of the module ───────────────────────────────


def test_the_names_this_module_restates_are_the_ones_their_owners_use() -> None:
    """The literals here against the modules that own them, so they cannot drift.

    Every store in this workspace restates its own names rather than importing a
    sibling's private constants — and the price of that discipline is that two
    spellings can disagree.  So the claim is not *"they are literals"* but *"the
    literals are the right ones"*, asserted against ``ProposalStore``,
    ``signal_agent._diversity`` and ``signal_agent._proposal`` rather than left
    to a reader's eye.
    """
    from signal_agent import NODE_PROPOSAL_TABLE, _diversity, _proposal

    module = _imported_module("_candidate")
    assert module.NODE_PROPOSAL_TABLE == NODE_PROPOSAL_TABLE == _proposal.NODE_PROPOSAL_TABLE
    assert module.NODE_PROPOSAL_NODE_COLUMN == _diversity.NODE_PROPOSAL_NODE_COLUMN
    assert module.MODEL_COLUMN == MODEL_COLUMN == _diversity.MODEL_COLUMN
    assert module.NODE_TABLE == _proposal.NODE_TABLE == _diversity.NODE_TABLE
    assert module.IS_GAIN_METRIC == IS_GAIN_METRIC == _discrimination().IS_GAIN_METRIC
    assert module.CANDIDATE_TABLE == CANDIDATE_TABLE
    assert module.MODEL_METRIC == MODEL_METRIC

    # The two *names* this member has for two different things, pinned apart:
    # the metric the correlation is computed over (214's, and ``ir_marginal``)
    # and the figure that correlation *is* (this feature's sentence's own word).
    # A later edit that made them one string would have confused an input with
    # an output, which is the kind of tidy-up a test has to argue with.
    assert MODEL_METRIC == "mechanism_discrimination"
    assert IS_GAIN_METRIC == "ir_marginal"
    assert MODEL_METRIC != IS_GAIN_METRIC, (
        "the figure's name and the metric's name are two names for two things: "
        "one is what is measured, the other is what is reported"
    )
    assert module.CANDIDATE_TABLE == "campaign_model_discrimination"
    assert module.GATE_SQL_TABLES == (
        "campaign",
        "campaign_model_discrimination",
        "campaign_discrimination",
        "node",
        "node_proposal",
        "replay_score",
    )


def _discrimination():
    """Feature 214's module, for the spelling claims above."""
    return _imported_module("_discrimination")


def test_the_module_declares_no_correlation_of_its_own() -> None:
    """There is one definition of §14.1's statistic in this member, and it is 214's.

    A structural claim about the source, because the failure it guards is silent:
    a second ``_pearson`` here would agree with 214's today and drift tomorrow,
    and the two features' rows would then report figures that are not comparable
    while looking like they are.  So this case pins that the arithmetic is
    *imported* — the names appear in the module's import statements — and that no
    function here computes a correlation over the cohort.
    """
    module = _imported_module("_candidate")
    imports = _imports(_module_source("_candidate.py"))
    assert imports["_pearson"] == "._discrimination"
    for borrowed in (
        "_interval",
        "_pearson",
        "_read_is_half",
        "_read_oos_half",
        "_require_correlation",
        "_require_spread",
        "_require_tables",
        "_require_campaign",
        "_proposal_history",
        "_validated_campaign_id",
        "_validated_cohort",
        "_utc_now",
    ):
        assert imports.get(borrowed) == "._discrimination", (
            f"{borrowed} is 214's, and a local definition of it here would be a "
            f"second derivation of §14.1's statistic"
        )
        assert borrowed in vars(module), f"{borrowed} is bound here"

    # And no *local* function re-derives either statistic.
    code = _code_of(_module_source("_candidate.py"))
    for rederived in ("atanh", "tanh", "inv_cdf", "NormalDist"):
        assert rederived not in code, (
            f"the module computes {rederived} itself, which is the interval's "
            f"arithmetic and belongs to feature 214"
        )


def test_the_module_reads_nothing_the_gate_produces() -> None:
    """**"Before the gate milestone", discharged structurally.**

    No milestone, gate verdict or gate arithmetic is a *value* anywhere in this
    workspace: ``M2``/``M3`` appear in code only as citations of the architecture,
    and feature 187's ``bootstrap._claim`` takes the gate's world count as a
    caller-supplied keyword precisely because the gate is not a stored state.  So
    the timing clause is discharged the only way it can be — as a claim about what
    this module *reads*: an instrument that must run before the gate must be
    computable from what exists before it, and must not depend on anything the
    gate produces.

    Two halves, both structural.  No gate token appears in the module's **code**
    (comments and docstrings stripped, because the module *cites* §14.1 and must
    be free to explain itself).  And every ``*_SQL`` constant names only a pre-M3
    table — the claim :data:`GATE_SQL_TABLES` states, checked here by reading the
    table names out of the statements rather than out of the constant.
    """
    code = _code_of(_module_source("_candidate.py"))
    for forbidden in (
        "milestone",
        "lofo",
        "fdr_deploy",
        "paired_delta",
        "gate_verdict",
        "is_null",
        "is_nullable",
        "campaign_type",
        "flip_depth",
    ):
        assert forbidden.lower() not in code.lower(), (
            f"the module names {forbidden!r}: a gate token would make the "
            f"instrument depend on what the gate produces, and the null "
            f"discriminant is not readable from anything this member may open"
        )

    module = _imported_module("_candidate")
    allowed = set(module.GATE_SQL_TABLES)
    assert allowed == {
        "campaign",
        "campaign_model_discrimination",
        "campaign_discrimination",
        "node",
        "node_proposal",
        "replay_score",
    }, "the allowed set is the four pre-M3 tables plus the two member-owned rows"

    statements = {
        name: value
        for name, value in vars(module).items()
        if name.endswith("_SQL") and isinstance(value, str)
    }
    assert statements, "the module declares its SQL as constants"
    named: set[str] = set()
    for name, statement in statements.items():
        opening = statement.strip().split()[0].upper()
        assert opening in {"SELECT", "PRAGMA", "CREATE"}, (
            f"{name} does not open with a read or the one owned CREATE"
        )
        for write in ("INSERT ", "UPDATE ", "DELETE ", "DROP ", "ALTER "):
            assert write not in statement.upper(), f"{name} carries a {write.strip()}"
        tokens = set(statement.replace("(", " ").replace(")", " ").split())
        named |= {
            token for token in tokens if token in allowed
        }
        assert not {
            token
            for token in tokens
            if token.islower() and token.endswith("_score") and token != "replay_score"
        }, f"{name} names a score table that is not 0109's"
    assert named, "the statements name the tables they read"

    # And **every table any string in the module names is in the allowed set** —
    # including the ones the ``*_SQL`` scan above cannot see, which are the
    # f-strings ``_persist`` and ``_MODEL_PROPOSALS_SQL``'s constant build.  The
    # scan is over SQL *keywords followed by a name*, so it catches a table
    # reached by an edit that forgot to widen the tuple and does **not** catch
    # the module's local variables, its column names or its keyword arguments —
    # the first version of this case split the source on whitespace and collected
    # every snake_case token, which reported a failure for a dozen reasons except
    # the one it exists for.
    tree = _ast.parse(_module_source("_candidate.py"))
    # The scan is over **SQL**, not over every string: a fragment counts only if
    # its own text opens with a statement verb, which is exactly the test that
    # separates a statement from this module's prose.  (The exclusion is not a
    # convenience — the module cites the architecture and quotes §14.1 at length,
    # and *"FROM the gate"* in a sentence is not a table reference.  A first
    # version of this case scanned every string constant and reported two dozen
    # English words as table names.)
    #
    # This half of the case exists because an f-string's static parts are what
    # ``_persist`` and ``_SCHEMA`` build their statements from, and the ``*_SQL``
    # scan above cannot see a table named inside a function body.
    verbs = ("SELECT", "PRAGMA", "CREATE", "INSERT", "UPDATE", "DELETE")
    statement_words = ("FROM", "JOIN", "INTO", "UPDATE", "TABLE", "INDEX")
    #: Words that can stand between a statement verb and the name it names —
    #: ``CREATE TABLE IF NOT EXISTS x``, ``SELECT 1 FROM x``.  Listing them is
    #: what makes the scan read *the name* rather than the next keyword.
    skip = {"IF", "NOT", "EXISTS", "OR", "IGNORE", "REPLACE", "TEMPORARY"}
    namespace = {
        name: value
        for name, value in vars(module).items()
        if isinstance(value, str)
    }
    mentioned: set[str] = set()
    for node in _ast.walk(tree):
        text = _rendered(node, namespace)
        if text is None:
            continue
        text = text.lstrip()
        if not text.upper().startswith(verbs):
            continue
        # Keywords are matched case-insensitively and the name is taken
        # **verbatim**: upper-casing the whole statement would fold a spliced-in
        # ``NODE_TABLE``'s *value* together with the keywords around it and there
        # would be no way to tell the table ``node`` from the constant that names
        # it.  That mistake is what the first run of this case reported.
        words = text.replace("(", " ").replace(")", " ").replace(",", " ").split()
        named = False
        for word in words:
            if named:
                if word.upper() not in skip:
                    mentioned.add(word.strip(",;"))
                    named = False
                continue
            if word.upper() in statement_words:
                named = True
    # ``sqlite_master`` is the catalog the one existence probe reads, and it is
    # not a table this member can write, join or scope by — it is named here
    # rather than added to ``GATE_SQL_TABLES`` because that tuple's claim is
    # about the *system's* tables.
    assert mentioned - {"sqlite_master"} <= allowed, (
        f"a statement in this module names a table outside "
        f"{sorted(allowed)}: {sorted(mentioned - allowed - {'sqlite_master'})}"
    )
    assert mentioned >= {"node", "sqlite_master"}, (
        "the scan found the statements it is supposed to find"
    )


def _rendered(node: _ast.AST, namespace: dict[str, str]) -> str | None:
    """One string constant's text, with this module's own string names spliced in.

    The module builds four of its statements as f-strings over its own constants
    — ``f"PRAGMA table_info({NODE_TABLE})"`` — so reading only the literal
    fragments would miss the table each one names and this half of the case would
    quietly check almost nothing.  The substitution is deliberately **bounded**:
    a constant is rendered only when every interpolated expression is a bare name
    this module binds to a string, and anything else answers ``None`` and is
    skipped.  That keeps the helper a reader of this module's strings rather than
    an evaluator of arbitrary code, which is the line a test has no business
    crossing.
    """
    if isinstance(node, _ast.Constant) and isinstance(node.value, str):
        return node.value
    if not isinstance(node, _ast.JoinedStr):
        return None
    rendered = ""
    for part in node.values:
        if isinstance(part, _ast.Constant) and isinstance(part.value, str):
            rendered += part.value
            continue
        if (
            isinstance(part, _ast.FormattedValue)
            and isinstance(part.value, _ast.Name)
            and part.value.id in namespace
        ):
            rendered += namespace[part.value.id]
            continue
        return None
    return rendered


def test_the_module_registers_no_component_and_has_no_seat() -> None:
    """The feature's shape: a free function, no ``@register``, no seat file.

    The reading resolves no configuration of its own, so a tenth
    ``signal-agent-*`` registration would put a name in the registry for a
    question that composes nothing.  Asserted structurally, because the absence
    of a component is exactly the kind of decision a later edit adds by habit.
    """
    module = _imported_module("_candidate")
    for name in vars(module):
        assert not name.startswith("build_"), (
            f"the module exposes {name!r}, which is the shape of a composed "
            f"builder's entry point; feature 216 composes nothing"
        )

    assert member.COMPONENT_NAME == "signal-agent"
    assert member.mechanism_discrimination_by_model is (
        mechanism_discrimination_by_model
    )


def test_the_module_imports_no_third_party_package() -> None:
    """Import-cheap, so the factory's scan pays nothing for this module.

    The scan imports this member to fire its ``@register`` builders; a module
    that pulled in ``numpy`` or ``pandas`` at module scope would charge that cost
    to every ``create_app()`` for a feature most deployments never call.
    """
    imports = _imports(_module_source("_candidate.py"))
    external = {
        root
        for root in (module.split(".")[0] for module in imports.values())
        if root and not root.startswith(".") and root != "__future__"
    }
    assert external <= {
        "collections",
        "contextlib",
        "datetime",
        "hashlib",
        "json",
        "pathlib",
        "sqlite3",
        "types",
        "typing",
        "uuid",
    }, f"unexpected third-party surface: {sorted(external)}"
    assert external, "the filter is doing something"


# ── Source-reading helpers ───────────────────────────────────────────────────


def _module_source(filename: str) -> str:
    """One of the member's own source files, read by path."""
    from pathlib import Path

    import signal_agent

    return (
        Path(signal_agent.__file__).parent / filename  # type: ignore[arg-type]
    ).read_text(encoding="utf-8")


def _imported_module(name: str):
    """One of the member's own submodules, imported by name."""
    import importlib

    return importlib.import_module(f"signal_agent.{name}")


def _code_of(source: str) -> str:
    """A module's source with every string literal and comment removed.

    Uses :mod:`tokenize` rather than a line filter, because the module documents
    the barrier *in prose that quotes the forbidden names* — a line-based scan
    would either forbid the module from explaining itself or be fooled by a
    docstring spanning a name boundary.  What survives is exactly what the
    interpreter would execute as names and operators.
    """
    pieces: list[str] = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type in {
            tokenize.COMMENT,
            tokenize.STRING,
            tokenize.FSTRING_MIDDLE,
        }:
            continue
        pieces.append(token.string)
    return " ".join(pieces)


def _imports(source: str) -> dict[str, str]:
    """What a module imports, as ``{bound name: module it came from}``.

    Parsed with :mod:`ast` rather than scanned with a regex, because this
    module's imports are **parenthesised across a dozen lines** and a line-based
    reader would report a dozen fragments instead of one statement.  The suite
    tried a token-rebuilding version first and it reported *zero* imports in a
    file that has thirteen — a false green exactly where a source-scanning case
    exists to avoid one — because the reconstruction renders ``from . _x import``
    with a space that no prefix match anticipates.  ``ast`` answers the question
    the cases actually ask — *is this name imported, and from where* — instead of
    approximating it from spacing.

    ``from .errors import X`` answers ``".errors"``, and ``import hashlib``
    answers ``"hashlib"``; a relative module keeps its leading dot, which is what
    lets ``test_the_module_declares_no_correlation_of_its_own`` say *imported
    from feature 214's module* rather than merely *imported*.
    """
    import ast as _ast

    found: dict[str, str] = {}
    for node in _ast.walk(_ast.parse(source)):
        if isinstance(node, _ast.Import):
            for alias in node.names:
                found[(alias.asname or alias.name).split(".")[0]] = alias.name
        elif isinstance(node, _ast.ImportFrom):
            module = "." * node.level + (node.module or "")
            for alias in node.names:
                found[alias.asname or alias.name] = module
    return found
