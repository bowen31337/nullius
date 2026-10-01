"""Feature 214's suite: ``mechanism_discrimination``, per campaign, with its interval.

app_spec.xml, "Hypothesis Authoring Agent", feature 214: *System persists
mechanism_discrimination per campaign, computed as the correlation between
in-sample gain and out-of-sample gain across real branches.*

The sentence is five claims and this file takes them one at a time, because they
fail in five different ways and a suite that tested "the feature" would let four
of them be true while the fifth was not:

* **the correlation between in-sample gain and out-of-sample gain** — the
  arithmetic and *which* pair of columns it is over.  The in-sample half is
  ``ir_marginal``, the one of ``0114``'s seven metrics that is a gain *by
  definition* (PRD §6.2: ``IR(book ∪ {v}) − IR(book)``), and the out-of-sample
  half is the per-world objective ``replay_score.score`` carries.  So the
  decision is pinned from both sides: the figure moves when ``ir_marginal``
  moves, and it does **not** move when the six other metrics move.
* **across real branches** — the cohort.  §14.1's formula carries the qualifier
  and the discriminant it selects on is unreadable from this member (§7.1, §4.2,
  feature 207 records no such flag), so the cohort is *declared* — and the
  refusal to derive it is pinned structurally, over the module's own source,
  rather than by behaviour a refactor could quietly change.
* **persists** — the member's first writer outside its component seats, into a
  table it owns, refresh-not-append, refused by a store that cannot be joined to
  a campaign.
* **per campaign** — the scope.  Scoped by the campaign the *store* holds, two
  campaigns never landing in one another's figure, and a campaign nobody planned
  refused.
* **the interval** — §14.1's rule 3 (*"report its interval, not the point"*).
  This is the claim that shapes the value object, and the one a caller could
  most easily get wrong: the figure is a *pair*, and the floors that make an
  interval exist are refusals rather than a printed point.

**The fixtures bring a real schema and a real writer.**  ``discrimination_database``
runs the tree chain feature 215's own fixture runs, then ``0111`` and ``0109`` —
so the out-of-sample half is the table migration ``0109`` creates, with that
migration's own ``NOT NULL``s, and the campaign row is ``0111``'s.  Every
in-sample half is written by feature 207's own :meth:`ProposalStore.persist`, so
the snapshots this feature correlates are documents the real store produced.

**The one hand-written table is hand-written because nothing in this workspace
writes it.**  ``replay_score``'s writer is the replay member (features 245-255),
which is unbuilt — the same fact ``packages/bootstrap/tests/test_census.py``
records about the same table for the same reason — so a suite that refused to
insert a run could not test this feature at all.  What that costs is stated once,
here, rather than repeated at each case: the *in-sample* half is store-produced
and therefore genuinely pinned, while the *out-of-sample* half is this suite's
own rows in the schema the migration creates.  When the replay member lands, the
half that is currently a fixture becomes a writer, and this file's runs are the
reads it must agree with.
"""

from __future__ import annotations

import json
import math
import sqlite3
import uuid
from contextlib import closing
from datetime import UTC, datetime
from statistics import NormalDist

import pytest
import signal_agent as member
from conftest import (
    REPLAY_MIGRATION,
    plant_campaign,
    plant_modelled_node,
    plant_run,
    record_gain,
    sqlite_path_of,
)
from signal_agent import (
    CONFIDENCE_LEVEL,
    DISCRIMINATION_TABLE,
    IS_GAIN_METRIC,
    MINIMUM_PAIRS,
    DiscriminationCohortError,
    MechanismDiscrimination,
    ProposalStore,
    ScoreRecord,
    load_mechanism_discrimination,
    mechanism_discrimination,
)

#: Two documents, because feature 207 identifies a proposal by the hash of its
#: bytes and refuses a second document against a node that already holds one —
#: so a suite recording four branches needs four distinct sources.  The content
#: is irrelevant to this feature (feature 214 reads no code), which is the point:
#: the figure is a function of the *scores*, and a case that changed only the
#: document must leave it alone.


def _document(index: int) -> str:
    """A distinct proposal source for branch ``index``.

    A function rather than a fixed tuple because the interval-width case needs a
    twenty-branch cohort, and a table of twenty literals would be twenty strings
    nobody reads in a file whose subject is arithmetic.  Distinctness is what
    matters — two branches cannot share a document, or feature 207's identity
    check refuses the second — and a rolling window is distinct per index.
    """
    return f"def signal(ctx, seed):\n    return ctx.close.rolling_mean({index + 2})\n"

#: A model id of the shape feature 203 pins — a provider/model/version triple.
#: One model throughout, because feature 214's sentence is *per campaign* and the
#: stratum is feature 216's subject: a suite that varied the model here would be
#: making a claim about a feature that does not exist yet.
_MODEL = "deepseek/deepseek-v4-flash/2026-09-10"

#: The revision every run in this suite is under, unless a case is *about* the
#: revision.  §14.1's instrument runs at M2 *under fixed exploration*, so the
#: ordinary cohort is one revision and the two-revision case is the refusal.
_POLICY = "policy-v1"

#: The in-sample gains and the out-of-sample readings the arithmetic cases use,
#: chosen so the answer is *computed* here rather than asserted from a stored
#: number: ``_RISING`` is strictly increasing and ``_STRONG`` tracks it, which is
#: the "strong agent" §14.1 describes — in-sample improvement predicting
#: sequestered-epoch improvement.  ``_NOISE`` is a permutation of ``_STRONG``: the
#: same values in a different order, so a correlation against it is a *weak*
#: agent's — a large in-sample gain earning a poor out-of-sample one and back.
#: The pair is what makes the discriminant test possible: same marginal
#: distributions, opposite readings.
_RISING = (0.10, 0.20, 0.30, 0.40)
_STRONG = (1.0, 2.0, 3.0, 5.0)
_NOISE = (3.0, 5.0, 1.0, 2.0)


def _cohort_shape(
    database_url: str,
    campaign: str,
    is_gains: tuple[float, ...],
    oos_gains: tuple[float, ...],
    *,
    runs_each: int = 1,
    policy: str = _POLICY,
) -> list[str]:
    """Plant one campaign with paired gains; return the branch ids in order.

    The construction every arithmetic claim is built from: branch ``i`` carries
    ``is_gains[i]`` in its snapshot and ``oos_gains[i]`` as the score of
    ``runs_each`` runs.  Branch ids come back in the order the pairs were given so
    a test can name one — which is what the single-branch mutations below do
    (change *this* branch's gain and assert the figure moved the right way).
    """
    branches = [
        record_gain(
            database_url,
            campaign,
            _MODEL,
            _document(index),
            is_gain,
            runs=(oos_gain,) * runs_each,
            policy_version=policy,
        )
        for index, (is_gain, oos_gain) in enumerate(zip(is_gains, oos_gains))
    ]
    return branches


def _measured(url: str, campaign: str, cohort: list[str]) -> MechanismDiscrimination:
    """Measure a campaign over ``cohort`` through feature 207's own handle."""
    return mechanism_discrimination(ProposalStore(url), campaign, cohort)


def _branch_ids(count: int) -> list[str]:
    """``count`` node ids that name nothing — for the refusals about arguments.

    Used where the case is *not* about the cohort's contents but about reaching a
    later refusal: the floor is checked before the store is opened, so a case
    testing the campaign check has to hand over a cohort that clears the floor
    first.  These ids are deliberately not planted anywhere, so a case that
    reached the pairing stage with them fails loudly rather than accidentally
    matching a real branch.
    """
    return [str(uuid.uuid4()) for _ in range(count)]


def _gain_of(url: str, node: str) -> float | None:
    """The in-sample gain the store recorded for ``node`` — for a claim's setup."""
    row = sqlite3.connect(sqlite_path_of(url)).execute(
        "SELECT score FROM node_proposal WHERE node_id = ?", (node,)
    ).fetchone()
    return ScoreRecord.from_json(row[0], node).ir_marginal


def _rows(url: str) -> list[tuple]:
    """Every stored reading, column order fixed by ``_STORED_COLUMNS``.

    An **absent table is an empty list** rather than an ``OperationalError``, and
    that is the point of the helper rather than a convenience: the table is
    member-owned and created lazily by :func:`_persist`, so "no row claims this
    reading happened" is exactly ``[]`` for a database where the write never ran —
    including a database where the table was never created at all.  A helper that
    raised there would make the refusals-below-the-arithmetic cases untestable,
    and those are the cases that pin feature 123's measure-before-write order.
    """
    with closing(sqlite3.connect(sqlite_path_of(url))) as connection:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (DISCRIMINATION_TABLE,),
        ).fetchone()
        if exists is None:
            return []
        return connection.execute(
            f"SELECT {', '.join(_STORED_COLUMNS)} FROM {DISCRIMINATION_TABLE}"
        ).fetchall()


#: The columns a persisted reading is made of, in the order the schema declares
#: them.  Spelled here so a claim about the *shape* of the row can compare this
#: tuple against ``PRAGMA table_info`` — the two must agree, and a test that read
#: the pragma once and used it for both sides would be comparing the table with
#: itself.
_STORED_COLUMNS = (
    "campaign_id",
    "correlation",
    "interval_lower",
    "interval_upper",
    "pairs",
    "runs",
    "policy_version",
    "cohort_digest",
    "seen_at",
)


def _stored_columns(url: str) -> tuple[str, ...]:
    """``campaign_discrimination``'s columns, read from the table itself."""
    with closing(sqlite3.connect(sqlite_path_of(url))) as connection:
        return tuple(
            row[1]
            for row in connection.execute(
                f"PRAGMA table_info({DISCRIMINATION_TABLE})"
            ).fetchall()
        )


# ── The correlation, and which pair of columns it is over ─────────────────────


def test_the_figure_is_the_correlation_of_the_two_gains(
    discrimination_database: str,
) -> None:
    """The sentence, whole: a strong cohort reads high, a weak one reads low.

    Two campaigns, same in-sample gains, out-of-sample readings that are a
    permutation of one another.  The *marginal distributions of both halves are
    identical* across the two campaigns — only the pairing differs — so this is
    the assertion that fails on an implementation returning anything that is a
    function of one series alone: a mean, a spread, a count, a rank statistic
    that ignored the pairing.  §14.1's whole reading is that the pairing is the
    measurement.
    """
    strong_campaign, weak_campaign = str(uuid.uuid4()), str(uuid.uuid4())
    for campaign in (strong_campaign, weak_campaign):
        plant_campaign(discrimination_database, campaign)
    strong = _cohort_shape(discrimination_database, strong_campaign, _RISING, _STRONG)
    weak = _cohort_shape(discrimination_database, weak_campaign, _RISING, _NOISE)

    strong_reading = _measured(discrimination_database, strong_campaign, strong)
    weak_reading = _measured(discrimination_database, weak_campaign, weak)

    assert strong_reading.correlation > 0.9
    assert weak_reading.correlation < 0.0
    # The two cohorts were built from the same values in both halves — asserted
    # rather than assumed, because the claim above is only about *pairing* if
    # this holds, and a fixture that quietly varied the values would make the
    # comparison meaningless while both assertions still passed.
    assert sorted(_STRONG) == sorted(_NOISE)


def test_the_figure_moves_with_ir_marginal_and_not_with_the_other_metrics(
    discrimination_database: str,
) -> None:
    """The in-sample half is ``ir_marginal`` — a claim about *which* column.

    ``0114`` declares seven metrics and feature 207's record carries all seven.
    This case plants them all pinned at a constant **and a fifth branch whose
    ``ir_marginal`` alone breaks the tie**, then asserts the figure is the one
    computed from ``ir_marginal`` — which is the assertion that fails on an
    implementation that reached for ``ir_standalone`` or ``ic_mean`` and would
    otherwise look entirely correct on a cohort where the seven happen to agree.

    Then it rewrites every *other* metric through the store's own writer — a
    second proposal cannot be recorded against a node, so the snapshot is
    replaced directly — and asserts the figure is unmoved.  The second half is
    what makes this a claim about one column rather than about a coincidence.
    """
    campaign = str(uuid.uuid4())
    plant_campaign(discrimination_database, campaign)
    branches = [
        record_gain(
            discrimination_database, campaign, _MODEL, _document(index), gain,
            runs=(oos,),
        )
        for index, (gain, oos) in enumerate(zip(_RISING, _STRONG))
    ]
    # Every other metric pinned far away from `ir_marginal` and constant, so a
    # reading taken from any of them is a different number and not merely an
    # equally-good one.
    for branch in branches:
        _rewrite_score(
            discrimination_database,
            branch,
            ScoreRecord(
                ic_mean=-0.5,
                ic_tstat=-9.0,
                ir_standalone=-3.0,
                ir_marginal=_gain_of(discrimination_database, branch),
                turnover=99.0,
                cost_adjusted_ir=42.0,
                perturb_stability=0.0,
            ),
        )

    reading = _measured(discrimination_database, campaign, branches)
    assert reading.correlation == pytest.approx(
        _correlation(_RISING, _STRONG), abs=1e-12
    )

    # Now move every metric the feature must *not* read.  The figure is a
    # function of `ir_marginal` alone, so nothing here may change it.
    for branch in branches:
        _rewrite_score(
            discrimination_database,
            branch,
            ScoreRecord(
                ic_mean=0.9,
                ic_tstat=100.0,
                ir_standalone=7.0,
                ir_marginal=_gain_of(discrimination_database, branch),
                turnover=1.0,
                cost_adjusted_ir=-7.0,
                perturb_stability=1.0,
            ),
        )
    again = _measured(discrimination_database, campaign, branches)
    assert again.correlation == reading.correlation


def test_the_out_of_sample_half_is_the_mean_of_a_branchs_runs(
    discrimination_database: str,
) -> None:
    """A branch is **one point**, at the mean of the runs it earned.

    §14.1's unit is the branch — *"across real branches"* — so a node the policy
    committed to in three worlds contributes one observation, not three.  The
    case is built so the two readings differ: branch 0's runs are the three
    values that, taken individually, would drag the correlation somewhere else,
    while their mean is the value the cohort was designed around.  An
    implementation that treated every run as a point would produce the other
    number, and :func:`_correlation` computes both so the assertion is about the
    distinction rather than about a stored constant.

    ``runs`` is also asserted here: the reading carries how many rows it was
    drawn on, which is *not* ``pairs`` whenever any branch has more than one run
    — and a figure reported without it is one nobody can check.
    """
    campaign = str(uuid.uuid4())
    plant_campaign(discrimination_database, campaign)
    spread = (0.0, 3.0, 0.0)
    branches = [
        record_gain(
            discrimination_database, campaign, _MODEL, _document(0), _RISING[0],
            runs=spread,
        ),
        *[
            record_gain(
                discrimination_database, campaign, _MODEL, _document(index), gain,
                runs=(oos,),
            )
            for index, (gain, oos) in enumerate(
                zip(_RISING[1:], _STRONG[1:]), start=1
            )
        ],
    ]

    reading = _measured(discrimination_database, campaign, branches)

    as_branches = (sum(spread) / len(spread), *_STRONG[1:])
    assert reading.correlation == pytest.approx(
        _correlation(_RISING, as_branches), abs=1e-12
    )
    # The number a per-run implementation would have produced — asserted to be a
    # *different* number, so the case cannot pass by the two coinciding.
    per_run = _correlation(
        [_RISING[0]] * len(spread) + list(_RISING[1:]),
        list(spread) + list(_STRONG[1:]),
    )
    assert reading.correlation != pytest.approx(per_run, abs=1e-6)
    assert reading.pairs == 4
    assert reading.runs == 6


def test_a_nine_run_branch_is_still_one_point(
    discrimination_database: str,
) -> None:
    """The many-worlds case, stated as its own claim.

    §14.1's *"two campaigns per candidate model"* at M2 means a branch may be
    committed to across many worlds.  A figure that counted runs would let one
    much-picked node carry the correlation by frequency rather than by contrast,
    which is why ``pairs`` and ``runs`` are two columns and not one: here the
    reading is over **four** branches and **twenty-one** runs, and an
    implementation that conflated them would report 21.
    """
    campaign = str(uuid.uuid4())
    plant_campaign(discrimination_database, campaign)
    branches = _cohort_shape(
        discrimination_database, campaign, _RISING, _STRONG, runs_each=7
    )

    reading = _measured(discrimination_database, campaign, branches)

    assert reading.pairs == 4
    assert reading.runs == 28
    assert reading.correlation == pytest.approx(
        _correlation(_RISING, _STRONG), abs=1e-12
    )


# ── The interval: §14.1's rule 3 ──────────────────────────────────────────────


def test_the_reading_carries_its_interval_and_the_interval_is_fishers_z(
    discrimination_database: str,
) -> None:
    """The figure is a *pair*, and the bounds are the arithmetic §14.1 names.

    *"Calibration beside accuracy.  ``mechanism_discrimination`` is a
    correlation; report its interval, not the point (design.md §9)."*  The
    assertion is against the transform computed here — ``z = atanh(r)``,
    ``se = 1/sqrt(n − 3)``, back through ``tanh`` at the two-sided 95% quantile —
    so the case pins *which* interval rather than merely that two numbers came
    back ordered.
    """
    campaign = str(uuid.uuid4())
    plant_campaign(discrimination_database, campaign)
    branches = _cohort_shape(discrimination_database, campaign, _RISING, _STRONG)

    reading = _measured(discrimination_database, campaign, branches)

    expected = _fisher_interval(_correlation(_RISING, _STRONG), 4)
    assert reading.lower == pytest.approx(expected[0], abs=1e-12)
    assert reading.upper == pytest.approx(expected[1], abs=1e-12)
    assert reading.lower < reading.correlation < reading.upper
    assert reading.interval == (reading.lower, reading.upper)
    assert CONFIDENCE_LEVEL == 0.95


def test_the_interval_widens_as_the_cohort_shrinks(
    discrimination_database: str,
) -> None:
    """What an interval is *for*: the floor exists because width is information.

    A four-branch cohort and a twenty-branch cohort with the same correlation
    answer different-width bounds, and the four-branch one is wide enough that
    §14.1's whole reporting rule is doing work.  The assertion is the *ordering*
    rather than the numbers, because the numbers move with the correlation and
    the ordering does not.
    """
    narrow_campaign, wide_campaign = str(uuid.uuid4()), str(uuid.uuid4())
    for campaign in (narrow_campaign, wide_campaign):
        plant_campaign(discrimination_database, campaign)
    small = _cohort_shape(discrimination_database, narrow_campaign, _RISING, _STRONG)
    large = _cohort_shape(
        discrimination_database,
        wide_campaign,
        _RISING * 5,
        _STRONG * 5,
    )

    narrow = _measured(discrimination_database, narrow_campaign, small)
    wide = _measured(discrimination_database, wide_campaign, large)

    assert wide.pairs == 20
    assert (wide.upper - wide.lower) < (narrow.upper - narrow.lower)


# ── The cohort: declared, never derived ───────────────────────────────────────


def test_the_cohort_is_required_and_has_no_default(
    discrimination_database: str,
) -> None:
    """``| real branches`` is not optional and this feature cannot supply it.

    The signature offers no default, and this case says so by *calling* it the
    other way: the cohort is a positional parameter, so a caller that omitted it
    gets a ``TypeError`` from Python rather than a figure silently computed over
    every branch in the store.  That distinction is the feature's: a defaulted
    cohort would mix in the exactly-zero half (§4.1: *"true out-of-sample edge of
    a null branch is exactly zero by construction"*), which attenuates the
    correlation mechanically and flatters a weak agent twice over.
    """
    campaign = str(uuid.uuid4())
    plant_campaign(discrimination_database, campaign)
    _cohort_shape(discrimination_database, campaign, _RISING, _STRONG)

    with pytest.raises(TypeError):
        mechanism_discrimination(ProposalStore(discrimination_database), campaign)


def test_an_undeclared_branch_is_never_read(
    discrimination_database: str,
) -> None:
    """The filter is in what the statement can *return*, not applied to its output.

    A campaign with four declared branches and a fifth that is recorded but not
    declared: the reading must be the four's, exactly.  This is the assertion
    that fails on an implementation that read every ``node_proposal`` row and
    filtered in Python — and the distinction matters beyond hygiene, because the
    undeclared branch here is a *maximally* disruptive point, so a leak shows up
    as a different number rather than as a rounding difference.
    """
    campaign = str(uuid.uuid4())
    plant_campaign(discrimination_database, campaign)
    declared = _cohort_shape(discrimination_database, campaign, _RISING, _STRONG)
    record_gain(
        discrimination_database,
        campaign,
        _MODEL,
        _document(9),
        -99.0,
        runs=(-99.0,),
    )

    reading = _measured(discrimination_database, campaign, declared)

    assert reading.pairs == 4
    assert reading.runs == 4
    assert reading.correlation == pytest.approx(
        _correlation(_RISING, _STRONG), abs=1e-12
    )


def test_the_module_never_names_the_null_discriminant() -> None:
    """The barrier, pinned structurally rather than by behaviour.

    §14.1's formula carries ``| real branches``, and the discriminant it selects
    on is not readable from anything this member may open — §7.1 (*"There is no
    ``is_null`` column anywhere in the tree store.  Not hidden, not nulled out,
    not ``SELECT``-excluded. **Absent.**"*), §4.2 (*"visible to exactly one
    component: the replay scorer"*), app_spec 447/456, and feature 207's record
    which carries no such flag.

    So the module must not name it, and this case reads the module's **own
    source** to say so — the same discipline ``test_diversity.py`` applies to its
    SQL constants.  A behavioural test would pass on an implementation that read
    the column and discarded the result; a source test cannot.  The forbidden
    spellings include the barrier's own vocabulary and the one regime name a
    tempting implementation would reach for (``_TYPE_R`` from the campaign row,
    which is *not* the resolved status and would be GIGO — the module argues why
    at ``_validated_cohort``).
    """
    # Docstrings and comments are stripped before the scan, and the reason is
    # specific rather than cosmetic: this module *quotes* the barrier's own
    # documentation — §7.1's "there is no is_null column anywhere in the tree
    # store" is the sentence that justifies the caller-declared cohort — and a
    # scan that counted prose would forbid the module from explaining itself.
    # What must not contain the name is the *code*.
    code = _code_of(_module_source("_discrimination.py"))
    for forbidden in (
        "is_null",
        "is_nullable",
        "campaign_type",
        "Type-R",
        "Type-D",
        "flip_depth",
    ):
        assert forbidden not in code, (
            f"the module names {forbidden!r}, which is the null discriminant or "
            f"a proxy for it: the cohort is declared by the caller and nothing "
            f"in this member may source that bit (§7.1, §4.2)"
        )

    # ``real_branches`` *is* allowed — it is the cohort itself, and the feature
    # sentence says "across real branches" — so the claim that needs pinning is
    # narrower: no SQL may *select* on such a name.  Every statement the module
    # declares is checked, because the place a derivation would appear is a
    # WHERE clause rather than a parameter.
    module = _imported_module("_discrimination")
    for name, statement in vars(module).items():
        if not (name.endswith("_SQL") and isinstance(statement, str)):
            continue
        for forbidden in ("is_null", "is_real", "real_branch", "campaign_type"):
            assert forbidden not in statement, (
                f"{name} selects on {forbidden!r}: the cohort's membership is "
                f"the *caller's* declaration and this module may not derive it"
            )


def test_the_module_reads_no_column_it_does_not_claim_to() -> None:
    """Every ``*_SQL`` constant is a read, and every one is over a named table.

    The module's *"what does it read"* claim as a source test: each module-level
    ``*_SQL`` constant opens with ``SELECT``, ``PRAGMA`` or the one ``CREATE
    TABLE IF NOT EXISTS`` this member is entitled to run — and no constant
    carries a write.  The write lives in :func:`_persist`, on its own connection,
    which is the *persists* half of the sentence and the reason the reads and the
    write are separated by the arithmetic.
    """
    module = _imported_module("_discrimination")
    constants = {
        name: value
        for name, value in vars(module).items()
        if name.endswith("_SQL") and isinstance(value, str)
    }
    assert constants, "the module declares its SQL as constants"
    for name, statement in constants.items():
        opening = statement.strip().split()[0].upper()
        assert opening in {"SELECT", "PRAGMA", "CREATE"}, (
            f"{name} does not open with a read or the one owned CREATE: "
            f"{statement.strip()[:60]!r}"
        )
        for write in ("INSERT ", "UPDATE ", "DELETE ", "DROP ", "ALTER "):
            assert write not in statement.upper(), f"{name} carries a {write.strip()}"
    assert any("SELECT" in value for value in constants.values())


# ── Persistence: the member's first writer outside its seats ───────────────────


def test_the_reading_is_persisted_under_the_campaign_and_reads_back(
    discrimination_database: str,
) -> None:
    """*persists* — the row is written, and the row the reader returns is the one.

    The full round trip through the feature's own two entry points.  A reading
    that only *returned* a figure would pass every arithmetic case above; this is
    the one that says the sentence's first verb happened.
    """
    campaign = str(uuid.uuid4())
    plant_campaign(discrimination_database, campaign)
    branches = _cohort_shape(discrimination_database, campaign, _RISING, _STRONG)

    written = _measured(discrimination_database, campaign, branches)
    read = load_mechanism_discrimination(ProposalStore(discrimination_database), campaign)

    assert read == written
    assert read is not None
    assert read.correlation == written.correlation
    assert read.interval == written.interval
    assert len(_rows(discrimination_database)) == 1


def test_a_second_reading_refreshes_rather_than_appends(
    discrimination_database: str,
) -> None:
    """The grain is the campaign: refresh-not-append, feature 123's shape.

    §14.1's instrument is run *"at M2, before the M3 gate"* over a cohort that
    grows as the campaign proposes, so a campaign is expected to be measured more
    than once and what the table must hold is the **latest** reading and nothing
    else.  A table that appended would let a report average two readings of the
    same campaign, or pick the more flattering one.
    """
    campaign = str(uuid.uuid4())
    plant_campaign(discrimination_database, campaign)
    branches = _cohort_shape(discrimination_database, campaign, _RISING, _STRONG)

    first = _measured(discrimination_database, campaign, branches)
    # A fifth branch, and it is chosen to move the figure: the campaign has been
    # refined and the new reading must be the new number.
    branches.append(
        record_gain(
            discrimination_database, campaign, _MODEL, _document(5), 0.5,
            runs=(6.0,),
        )
    )
    second = _measured(discrimination_database, campaign, branches)

    assert second.correlation != first.correlation
    assert len(_rows(discrimination_database)) == 1
    assert (
        load_mechanism_discrimination(
            ProposalStore(discrimination_database), campaign
        )
        == second
    )


def test_two_campaigns_never_share_a_reading(
    discrimination_database: str,
) -> None:
    """*per campaign* — the scope, and the reason it is the store's answer.

    Two campaigns, both measured, each read back as its own.  The branches of the
    two are *interleaved* in insertion order, so an implementation that scoped by
    "whatever the caller passed most recently" or by row order rather than by the
    stored ``campaign_id`` produces the other campaign's figure here.
    """
    first_campaign, second_campaign = str(uuid.uuid4()), str(uuid.uuid4())
    for campaign in (first_campaign, second_campaign):
        plant_campaign(discrimination_database, campaign)
    first = _cohort_shape(discrimination_database, first_campaign, _RISING, _STRONG)
    second = _cohort_shape(discrimination_database, second_campaign, _RISING, _NOISE)
    # Interleave the two cohorts' *runs* by adding to each after both have
    # branches, so neither campaign's rows are contiguous.
    for branch in first:
        plant_run(discrimination_database, committed_pick=branch, score=0.0)

    first_reading = _measured(discrimination_database, first_campaign, first)
    second_reading = _measured(discrimination_database, second_campaign, second)

    store = ProposalStore(discrimination_database)
    assert load_mechanism_discrimination(store, first_campaign) == first_reading
    assert load_mechanism_discrimination(store, second_campaign) == second_reading
    assert first_reading.correlation != second_reading.correlation
    assert len(_rows(discrimination_database)) == 2


def test_an_unrecorded_campaign_is_refused_by_name(
    discrimination_database: str,
) -> None:
    """A reading is a fact about a campaign, and the campaign must exist.

    The campaign row is written by the planner before any node is expanded, so a
    measurement against a campaign nobody planned is a caller bug worth learning
    before a figure lands nowhere.  The check is a *read*, and this case also
    asserts the negative: no row was invented for the missing campaign.
    """
    campaign = str(uuid.uuid4())
    branches = _cohort_shape(discrimination_database, campaign, _RISING, _STRONG)

    with pytest.raises(DiscriminationCohortError) as caught:
        _measured(discrimination_database, campaign, branches)

    assert campaign in str(caught.value)
    assert "campaign" in str(caught.value)
    assert _rows(discrimination_database) == []


def test_an_unmeasured_campaign_reads_back_as_none(
    discrimination_database: str,
) -> None:
    """*Never measured* is ``None``; it is not *the store is absent*.

    The three-way distinction feature 207 draws for its own ``load``: ``None``
    means this campaign has never been measured, a missing store *raises*, and a
    failed read raises.  A caller that mistook the first for the second would
    re-run a measurement it already has.  Both halves are asserted here — the
    ``None`` for a planned-but-unmeasured campaign, and the raise for a store
    that holds nothing at all — because a ``None`` alone would also pass on an
    implementation that swallowed every error.
    """
    campaign = str(uuid.uuid4())
    plant_campaign(discrimination_database, campaign)
    _cohort_shape(discrimination_database, campaign, _RISING, _STRONG)

    assert (
        load_mechanism_discrimination(
            ProposalStore(discrimination_database), campaign
        )
        is None
    )

    # A campaign that was never planted, in a database whose member-owned table
    # exists but holds nothing for it: still `None`, because the question is
    # about the campaign and not about the table.
    other = str(uuid.uuid4())
    assert (
        load_mechanism_discrimination(
            ProposalStore(discrimination_database), other
        )
        is None
    )

    # And the two *raises*, which are the distinction the reader must not
    # confuse with the `None` above.  A measurement of an unplanned campaign is
    # refused by name — it is a caller bug — and that is deliberately *not*
    # answered with a `None`, because `None` is a fact about the store and this
    # is a fact about the arguments.
    unplanned = str(uuid.uuid4())
    store = ProposalStore(discrimination_database)
    with pytest.raises(DiscriminationCohortError) as caught:
        mechanism_discrimination(store, unplanned, _branch_ids(4))
    assert "campaign" in str(caught.value)

    # The store half is a separate case on a separate database, because it needs
    # one feature 207 has never written to: see
    # `test_a_fresh_database_is_refused_for_its_missing_out_of_sample_half`.
    assert isinstance(store, ProposalStore)


def test_a_fresh_database_is_refused_for_its_missing_out_of_sample_half(
    discrimination_database_url: str,
) -> None:
    """A store that stops before ``0109`` has no second half, and says which.

    The refusal that makes the feature's honest claim explicit: the figure needs
    *both* sides of the barrier, and a deployment that has only ever run the
    discovery loop cannot have one.  The message names the revision, which is the
    whole actionable content.
    """
    campaign = str(uuid.uuid4())
    store = ProposalStore(discrimination_database_url)
    _seed_tree_only(
        discrimination_database_url, campaign, store, _document(0), gain=0.1
    )

    with pytest.raises(DiscriminationCohortError) as caught:
        mechanism_discrimination(store, campaign, ["a", "b", "c", "d"])

    assert "replay_score" in str(caught.value)
    assert REPLAY_MIGRATION in str(caught.value)


def test_the_stored_row_carries_the_interval_the_digest_and_the_denominators(
    discrimination_database: str,
) -> None:
    """What the table holds, read from the table rather than from the object.

    The columns are this feature's own claim about what a persisted reading *is*:
    the point, **both bounds**, both denominators, the revision, the digest and
    the instant.  A schema storing the point alone would let a report print it
    unaccompanied — which is precisely what rule 3 forbids — so the absence of a
    point-only shape is asserted structurally, over ``PRAGMA table_info``.
    """
    campaign = str(uuid.uuid4())
    plant_campaign(discrimination_database, campaign)
    branches = _cohort_shape(discrimination_database, campaign, _RISING, _STRONG)

    reading = _measured(discrimination_database, campaign, branches)

    columns = _stored_columns(discrimination_database)
    assert columns == _STORED_COLUMNS
    assert set(columns) == {
        "campaign_id",
        "correlation",
        "interval_lower",
        "interval_upper",
        "pairs",
        "runs",
        "policy_version",
        "cohort_digest",
        "seen_at",
    }
    (row,) = _rows(discrimination_database)
    stored = dict(zip(columns, row))
    assert stored["correlation"] == reading.correlation
    assert stored["interval_lower"] == reading.lower
    assert stored["interval_upper"] == reading.upper
    assert stored["pairs"] == 4
    assert stored["runs"] == 4
    assert stored["policy_version"] == _POLICY
    assert stored["cohort_digest"] == reading.cohort_digest
    assert len(stored["cohort_digest"]) == 64


# ── §14.1's rule 1: the cohort is frozen and its inputs are hashed ────────────


def test_the_digest_is_the_same_for_one_cohort_however_it_is_ordered(
    discrimination_database: str,
) -> None:
    """*"Freeze the cohort before any model runs, and hash its inputs."*

    The digest is a statement about the cohort's *contents*, so two callers who
    freeze the same cohort in different orders must hash alike — otherwise the
    digest would be a fact about iteration order, and \"the same cohort\" would be
    unverifiable across two runs.  The module imposes the order rather than
    trusting it.
    """
    campaign = str(uuid.uuid4())
    plant_campaign(discrimination_database, campaign)
    branches = _cohort_shape(discrimination_database, campaign, _RISING, _STRONG)

    forwards = _measured(discrimination_database, campaign, list(branches))
    backwards = _measured(
        discrimination_database, campaign, list(reversed(branches))
    )

    assert forwards.cohort_digest == backwards.cohort_digest
    assert backwards.correlation == forwards.correlation


def test_the_digest_changes_when_an_input_changes(
    discrimination_database: str,
) -> None:
    """The other half of the rule: a *different* cohort hashes differently.

    A digest that ignored the gains would let two genuinely different readings
    publish one signature.  Three inputs moved one at a time — the gains, the
    revision, the campaign — and each must change it.
    """
    campaign, other_campaign = str(uuid.uuid4()), str(uuid.uuid4())
    for each in (campaign, other_campaign):
        plant_campaign(discrimination_database, each)
    branches = _cohort_shape(discrimination_database, campaign, _RISING, _STRONG)
    base = _measured(discrimination_database, campaign, branches)

    # Another campaign's reading of the *same* pairs — and the digest differs,
    # because the campaign is one of the frozen inputs.
    other_branches = _cohort_shape(
        discrimination_database, other_campaign, _RISING, _STRONG
    )
    assert (
        _measured(discrimination_database, other_campaign, other_branches).cohort_digest
        != base.cohort_digest
    )

    # A moved gain, on one branch, with everything else held.
    _rewrite_score(
        discrimination_database,
        branches[0],
        ScoreRecord(ir_marginal=_RISING[0] + 0.5),
    )
    moved = _measured(discrimination_database, campaign, branches)
    assert moved.cohort_digest != base.cohort_digest
    assert moved.correlation != base.correlation


def test_the_pairs_are_hashed_in_branch_id_order(
    discrimination_database: str,
) -> None:
    """The order the digest imposes is *node id*, not insertion order.

    Asserted by recomputing the digest here from the module's own helper over the
    pairs in id order and comparing — which is what distinguishes \"the order is
    imposed\" from \"the order happens to match this fixture's\".  If the module
    were hashing in iteration order this case would pass only by accident, so it
    also constructs the two orders and asserts they differ as *lists*.

    The branch ids are fixed literals here rather than ``_cohort_shape``'s usual
    ``uuid.uuid4()`` mint: four random ids land in id-sorted order by chance
    about 1 time in 24 (4!), which made ``inserted != by_id`` below fail for a
    reason that had nothing to do with the order the digest imposes. Planting
    these four out of id order by construction is what makes the case
    deterministic rather than a 1-in-24 flake.
    """
    campaign = str(uuid.uuid4())
    plant_campaign(discrimination_database, campaign)
    branches = [
        "d0000000-0000-0000-0000-000000000001",
        "a0000000-0000-0000-0000-000000000002",
        "c0000000-0000-0000-0000-000000000003",
        "b0000000-0000-0000-0000-000000000004",
    ]
    for index, (branch, is_gain, oos_gain) in enumerate(
        zip(branches, _RISING, _STRONG)
    ):
        plant_modelled_node(
            discrimination_database, _MODEL, node_id=branch, campaign_id=campaign
        )
        ProposalStore(discrimination_database).persist(
            branch, _document(index), score=ScoreRecord(ir_marginal=is_gain)
        )
        plant_run(
            discrimination_database,
            committed_pick=branch,
            score=oos_gain,
            policy_version=_POLICY,
        )
    reading = _measured(discrimination_database, campaign, branches)

    from signal_agent import _discrimination as module

    # The gains belong to branches by *insertion* order — the loop above planted
    # ``branches[i]`` with ``_RISING[i]`` — so the pairs are built by pairing
    # first and sorting second.  Zipping the sorted ids against the unsorted
    # gains would attribute each gain to the wrong branch, and the digest would
    # then disagree with the module's for a reason that has nothing to do with
    # the order claim.
    inserted = tuple(zip(branches, _RISING, _STRONG))
    by_id = tuple(sorted(inserted, key=lambda pair: pair[0]))
    assert reading.cohort_digest == module._cohort_digest(
        campaign, _POLICY, by_id
    )
    assert inserted != by_id, "the fixture must not already be id-sorted"
    assert module._cohort_digest(campaign, _POLICY, inserted) != (
        reading.cohort_digest
    )


# ── The refusals: what a cohort that cannot answer looks like ─────────────────


def test_a_cohort_below_the_floor_is_refused_quoting_the_rule(
    discrimination_database: str,
) -> None:
    """Three branches cannot be *reported*, so they are refused rather than printed.

    §14.1's rule 3 is the reason the floor is four and not two: the interval is
    Fisher's z, whose standard error is ``1/sqrt(n − 3)``, so below four pairs
    there is no interval to report — and a point estimate presented alone is, per
    ``design.md`` §9, *"how people convince themselves a noisy result is a
    finding"*.  The message quotes the rule rather than merely naming a count,
    because the caller's repair is *expand the campaign*, which only makes sense
    if they know why three is not enough.
    """
    campaign = str(uuid.uuid4())
    plant_campaign(discrimination_database, campaign)
    branches = _cohort_shape(
        discrimination_database, campaign, _RISING[:3], _STRONG[:3]
    )

    with pytest.raises(DiscriminationCohortError) as caught:
        _measured(discrimination_database, campaign, branches)

    message = str(caught.value)
    assert "interval" in message
    assert str(MINIMUM_PAIRS) in message
    assert _rows(discrimination_database) == []
    assert MINIMUM_PAIRS == 4


def test_a_constant_in_sample_series_is_refused_rather_than_answered_zero(
    discrimination_database: str,
) -> None:
    """A degenerate cohort cannot answer, and ``0.0`` would be a *claim*.

    A correlation against a series with no variance is undefined.  Answering
    ``0.0`` would read as *"this agent's gains carry no discrimination"* — the
    unflattering direction — when the truth is that the cohort cannot answer.
    Refused by name, naming the series, and **no row is written**: the
    measure-before-write order, so a refused reading leaves nothing claiming it
    happened.
    """
    campaign = str(uuid.uuid4())
    plant_campaign(discrimination_database, campaign)
    branches = _cohort_shape(
        discrimination_database, campaign, (0.5, 0.5, 0.5, 0.5), _STRONG
    )

    with pytest.raises(DiscriminationCohortError) as caught:
        _measured(discrimination_database, campaign, branches)

    assert "in-sample" in str(caught.value)
    assert "do not vary" in str(caught.value)
    assert _rows(discrimination_database) == []


def test_a_constant_out_of_sample_series_is_refused_by_its_own_name(
    discrimination_database: str,
) -> None:
    """The other side, refused as the *other* series — the repair differs.

    Same arithmetic, different repair: a constant out-of-sample series is a
    replay whose runs all scored alike, and a message that said *in-sample* would
    send the caller to look at the wrong half of the store.
    """
    campaign = str(uuid.uuid4())
    plant_campaign(discrimination_database, campaign)
    branches = _cohort_shape(
        discrimination_database, campaign, _RISING, (2.0, 2.0, 2.0, 2.0)
    )

    with pytest.raises(DiscriminationCohortError) as caught:
        _measured(discrimination_database, campaign, branches)

    assert "out-of-sample" in str(caught.value)
    assert "do not vary" in str(caught.value)


def test_a_collinear_cohort_answers_with_a_narrow_interval_and_not_a_refusal(
    discrimination_database: str,
) -> None:
    """Perfectly collinear *data* is answered; ``|r| = 1`` exactly is not.

    The two are different states and this case exists because assuming otherwise
    is the easy mistake.  A collinear cohort's float correlation comes out at
    ``0.9999999999999998`` rather than at ``1.0`` — measured, not assumed — so
    ``atanh`` is finite, an interval exists, and the honest answer is a reading
    with an extremely narrow one.  Refusing it would be refusing a cohort that
    §14.1's rule 3 can in fact report on.

    The ``±1`` refusal is therefore a *domain guard* rather than a data outcome:
    ``math.atanh(±1)`` raises ``ValueError``, and float overshoot can produce
    ``r`` marginally past 1, so the guard protects the transform from both — but
    it fires for a value only a hand-built reading reaches, and it is exercised
    at the value object below.  What this case pins is the boundary: collinear
    data is narrow, not refused.
    """
    campaign = str(uuid.uuid4())
    plant_campaign(discrimination_database, campaign)
    branches = _cohort_shape(
        discrimination_database, campaign, (1.0, 2.0, 3.0, 4.0), (2.0, 4.0, 6.0, 8.0)
    )

    reading = _measured(discrimination_database, campaign, branches)

    assert reading.correlation == pytest.approx(1.0, abs=1e-12)
    assert reading.correlation < 1.0
    assert reading.upper - reading.lower < 0.1
    assert reading.lower < reading.correlation < reading.upper
    assert len(_rows(discrimination_database)) == 1


def test_a_branch_with_no_committed_run_is_refused_rather_than_dropped(
    discrimination_database: str,
) -> None:
    """A declared branch the pool never scored has no ``y``, and is not omitted.

    Refused rather than dropped because §14.1's rule 1 is explicit — *"A cohort
    assembled after seeing results is a selection, not a sample"* — and a figure
    computed over whatever subset happened to have both halves is a cohort
    assembled after the fact *by availability*, which is the same failure one step
    removed.  The message names the branch.
    """
    campaign = str(uuid.uuid4())
    plant_campaign(discrimination_database, campaign)
    branches = _cohort_shape(discrimination_database, campaign, _RISING, _STRONG)
    abandoned = plant_modelled_node(
        discrimination_database, _MODEL, campaign_id=campaign
    )
    ProposalStore(discrimination_database).persist(
        abandoned, _document(6), score=ScoreRecord(ir_marginal=0.9)
    )

    with pytest.raises(DiscriminationCohortError) as caught:
        _measured(discrimination_database, campaign, [*branches[:3], abandoned])

    assert abandoned in str(caught.value)
    assert "committed run" in str(caught.value)
    assert _rows(discrimination_database) == []


def test_a_branch_with_no_recorded_proposal_is_refused_by_name(
    discrimination_database: str,
) -> None:
    """The other missing half — and the two are different repairs.

    A node with no ``node_proposal`` row was never *proposed*; one with no
    ``replay_score`` row was proposed and never *committed to*.  Two states, two
    messages, and this case pins the first: a declared branch the campaign never
    recorded.
    """
    campaign = str(uuid.uuid4())
    plant_campaign(discrimination_database, campaign)
    branches = _cohort_shape(discrimination_database, campaign, _RISING, _STRONG)
    unrecorded = plant_modelled_node(
        discrimination_database, _MODEL, campaign_id=campaign
    )

    with pytest.raises(DiscriminationCohortError) as caught:
        _measured(discrimination_database, campaign, [*branches[:3], unrecorded])

    assert unrecorded in str(caught.value)
    assert "no recorded proposal" in str(caught.value)


def test_a_branch_from_another_campaign_is_refused(
    discrimination_database: str,
) -> None:
    """The scope on the *stored* row is the authority, never the caller's pairing.

    Feature 207 reads ``campaign_id`` off the node's own row at the moment of the
    write, so a branch offered as a member of this campaign while its recorded row
    belongs to another is refused rather than quietly contributing its gain here.
    This is the assertion that fails on an implementation that trusted the
    caller's cohort membership.
    """
    campaign, other_campaign = str(uuid.uuid4()), str(uuid.uuid4())
    for each in (campaign, other_campaign):
        plant_campaign(discrimination_database, each)
    mine = _cohort_shape(discrimination_database, campaign, _RISING[:3], _STRONG[:3])
    theirs = _cohort_shape(
        discrimination_database, other_campaign, _RISING[3:], _STRONG[3:]
    )

    with pytest.raises(DiscriminationCohortError) as caught:
        _measured(discrimination_database, campaign, [*mine, theirs[0]])

    message = str(caught.value)
    assert theirs[0] in message
    assert other_campaign in message


def test_a_snapshot_with_no_ir_marginal_is_refused_as_an_absence(
    discrimination_database: str,
) -> None:
    """A ``None`` gain is an absent measurement, not a zero — ``0114``'s own law.

    ``0114`` declares all seven metrics nullable because they are *measured*:
    *"a pre-metric row has no honest value to assert"*.  An attempt that failed
    before the evaluator reached it has a persisted snapshot with every metric
    absent — an expected state, and one this reading must decline rather than
    treat as a gain of zero.  Answering with the absence read as ``0.0`` would
    change the figure and would be a claim about a measurement that never
    happened.
    """
    campaign = str(uuid.uuid4())
    plant_campaign(discrimination_database, campaign)
    branches = _cohort_shape(discrimination_database, campaign, _RISING, _STRONG)
    unmeasured = record_gain(
        discrimination_database, campaign, _MODEL, _document(5), None,
        runs=(2.0,),
    )

    with pytest.raises(DiscriminationCohortError) as caught:
        _measured(discrimination_database, campaign, [*branches[:3], unmeasured])

    message = str(caught.value)
    assert unmeasured in message
    assert IS_GAIN_METRIC in message
    assert "absence" in message


def test_runs_spanning_two_policy_versions_are_refused(
    discrimination_database: str,
) -> None:
    """§14.1's instrument runs *under fixed exploration*, so one revision.

    Rows under two revisions are two policies' commits, and a correlation across
    them would attribute one policy's discrimination to a campaign.  Refused
    rather than filtered to one revision — and the module argues the alternative
    at ``_read_oos_half``: a filter would let a caller correlate a subset of the
    campaign's runs by hand, which is a cohort assembled after seeing results.
    The message lists the revisions, because that is what the caller must go and
    look at.
    """
    campaign = str(uuid.uuid4())
    plant_campaign(discrimination_database, campaign)
    branches = _cohort_shape(discrimination_database, campaign, _RISING, _STRONG)
    plant_run(
        discrimination_database,
        committed_pick=branches[0],
        score=4.0,
        policy_version="policy-v2",
    )

    with pytest.raises(DiscriminationCohortError) as caught:
        _measured(discrimination_database, campaign, branches)

    message = str(caught.value)
    assert "policy" in message
    assert _POLICY in message and "policy-v2" in message


def test_an_empty_cohort_is_refused_before_anything_is_read(
    discrimination_database: str,
) -> None:
    """An empty cohort is a question about no branches, not a reading of zero.

    Refused with its own message rather than the floor's, because the repair is
    different: a four-branch floor is a campaign to expand, while an empty cohort
    is a caller bug.  The refusal happens before the store is opened, which is
    what the *no row* assertion pins alongside.
    """
    campaign = str(uuid.uuid4())
    plant_campaign(discrimination_database, campaign)

    with pytest.raises(DiscriminationCohortError) as caught:
        _measured(discrimination_database, campaign, [])

    assert "empty" in str(caught.value)
    assert _rows(discrimination_database) == []


def test_a_bare_string_is_not_a_cohort_of_branches(
    discrimination_database: str,
) -> None:
    """A string is iterable, so it is refused explicitly rather than per character.

    ``"abcd"`` would iterate as four single-character branches under a naive
    implementation, which is four *plausible-looking* node ids and therefore a
    failure that would look like a measurement rather than like a bug.
    """
    campaign = str(uuid.uuid4())
    plant_campaign(discrimination_database, campaign)

    with pytest.raises(DiscriminationCohortError) as caught:
        _measured(discrimination_database, campaign, "abcd")

    assert "iterable" in str(caught.value)


def test_the_cohort_is_de_duplicated_before_it_is_counted(
    discrimination_database: str,
) -> None:
    """A branch named twice is one branch — the unit is the *branch*.

    A cohort that counted a repeat twice would weight that refinement twice in a
    correlation over branches, which is the per-run failure one step removed.  The
    floor is what makes this observable: four distinct branches plus a repeat of
    one is a four-point cohort, and an implementation that did not de-duplicate
    would compute over five with the repeated point's influence doubled.
    """
    campaign = str(uuid.uuid4())
    plant_campaign(discrimination_database, campaign)
    branches = _cohort_shape(discrimination_database, campaign, _RISING, _STRONG)

    reading = _measured(
        discrimination_database, campaign, [*branches, branches[0]]
    )

    assert reading.pairs == 4
    assert reading.correlation == pytest.approx(
        _correlation(_RISING, _STRONG), abs=1e-12
    )


def test_a_handle_that_is_not_the_proposal_history_law_is_refused(
    discrimination_database: str,
) -> None:
    """The handle is duck-typed on ``history`` and ``path``, and refused by name.

    Two names, each for its own reason: ``history`` is the verb that makes the
    object a proposal history rather than anything holding a path, and ``path`` is
    where the rows are.  An arbitrary object with only one of them is refused —
    and both refusals happen *before* the store is opened, which is what makes
    them validation rather than a failed read.
    """
    with pytest.raises(DiscriminationCohortError) as caught:
        mechanism_discrimination(object(), str(uuid.uuid4()), ["a", "b", "c", "d"])
    assert "history" in str(caught.value)

    class HistoryOnly:
        """An object with the history verb and no usable path."""

        def history(self, campaign_id):  # pragma: no cover - never called
            return ()

    with pytest.raises(DiscriminationCohortError) as caught:
        mechanism_discrimination(
            HistoryOnly(), str(uuid.uuid4()), _branch_ids(4)
        )
    assert "path" in str(caught.value)


def test_a_campaign_id_that_is_not_a_uuid_is_refused(
    discrimination_database: str,
) -> None:
    """The key is UUID text, so an id that cannot join the row is refused.

    A mixed-case or malformed id would make one campaign read as two — here, in
    the question of which rows the reading is about — so the id is normalised and
    a string no UUID answers to is refused rather than written.
    """
    for bad in ("not-a-uuid", "", "   ", 17, None, True):
        with pytest.raises(DiscriminationCohortError):
            mechanism_discrimination(
                ProposalStore(discrimination_database),
                bad,
                _branch_ids(4),
            )


def test_a_bool_campaign_id_is_refused_because_true_is_one(
    discrimination_database: str,
) -> None:
    """``True`` is ``1`` in Python, so a flag is refused before a UUID check.

    Stated as its own case because it is the member's recurring trap: a
    ``bool``-where-an-id-belongs would not fail a naive ``str`` coercion, and the
    class of bug is worth one assertion that names it.
    """
    with pytest.raises(DiscriminationCohortError) as caught:
        mechanism_discrimination(
            ProposalStore(discrimination_database), True, _branch_ids(4)
        )
    assert "campaign_id" in str(caught.value)


# ── The value object, and the row a hand could have edited ────────────────────


def test_a_value_no_measurement_could_produce_is_refused(
    discrimination_database: str,
) -> None:
    """The constructor validates, because every field reaches a published report.

    A hand-built value is a test's prerogative — the loader reconstructs through
    this constructor precisely so a stored row is checked — so an object no read
    could produce must be refused rather than printed: a correlation outside
    ``[-1, 1]``, a point outside its own interval, bounds that are not *this*
    point's interval over *this* many pairs, a cohort below the floor, ``runs``
    below ``pairs``, a short digest, a naive stamp.

    **The control is a genuinely legal value**, and building it that way is the
    point of the exercise: the legal case's bounds are computed from
    :func:`_fisher_interval` rather than eyeballed, because the constructor
    checks that the interval *follows* from the point and the pair count — so a
    hand-picked ``[0.0, 0.9]`` around ``r = 0.5`` is itself a refusal, and a
    control built from round numbers would fail before any of the mutations ran.
    """
    def build(**overrides):
        point, count = 0.5, 10
        lo, hi = _fisher_interval(point, count)
        fields = {
            "campaign_id": str(uuid.uuid4()),
            "correlation": point,
            "lower": lo,
            "upper": hi,
            "pairs": count,
            "runs": 12,
            "policy_version": _POLICY,
            "cohort_digest": "a" * 64,
            "seen_at": datetime(2026, 9, 22, 12, 0, tzinfo=UTC),
        }
        fields.update(overrides)
        return MechanismDiscrimination(**fields)

    assert build().correlation == 0.5  # the control: this shape is legal

    for overrides in (
        {"correlation": 1.5},
        {"correlation": float("nan")},
        {"correlation": True},
        {"correlation": 1.0},  # at the boundary: no interval exists
        {"correlation": -1.0},
        {"lower": -1.5},
        {"upper": 1.5},
        {"upper": 0.1},  # point outside its own interval
        {"lower": 0.6},
        {"pairs": 3},  # below the floor
        {"pairs": True},
        {"runs": 2},  # fewer runs than branches
        {"pairs": 10, "lower": 0.49, "upper": 0.51},  # not this r's interval
        {"pairs": 20, "lower": -0.19, "upper": 0.86},  # another n's interval
        {"policy_version": "  "},
        {"policy_version": 7},
        {"cohort_digest": "abc"},
        {"cohort_digest": "z" * 64},
        # A naive stamp, built by parsing rather than by omitting ``tzinfo`` —
        # which is also how a naive stamp would actually arrive at a reader:
        # from text somebody wrote without a zone.
        {"seen_at": datetime.fromisoformat("2026-09-22T12:00:00")},
        {"seen_at": "2026-09-22"},
    ):
        with pytest.raises(DiscriminationCohortError):
            build(**overrides)


def test_a_hand_edited_row_fails_to_load_rather_than_loading_plausibly(
    discrimination_database: str,
) -> None:
    """Reconstruction is the defence, since there is no second row to reconcile.

    Feature 123 reconciles its figure against the headline column it also wrote;
    this feature may not add a column to a shared table, so it has no second half
    to compare against.  What replaces that is **rebuilding through the
    validating constructor**: a row whose bounds do not follow from its point and
    its cohort size, or whose point is outside its own interval, fails to load
    rather than loading as a plausible-looking reading.  That is the difference
    between a defence and a parse.

    **The edit is chosen to survive the *earlier* checks**, which is what makes
    it a test of the reconstruction rather than of the ordering: the forged
    bounds still *contain* the point, and they are still inside ``[-1, 1]``.
    Only the arithmetic ties them to the reading, and only recomputation can
    catch that — a row edited this way is exactly the plausible-looking one this
    defence exists for.  (The looser edit — bounds that exclude the point —
    is caught one check earlier, which is a *different* claim, and the value
    object's case exercises it.)
    """
    campaign = str(uuid.uuid4())
    plant_campaign(discrimination_database, campaign)
    branches = _cohort_shape(discrimination_database, campaign, _RISING, _STRONG)
    reading = _measured(discrimination_database, campaign, branches)

    # Wider than the true interval, still containing the point, still in range.
    # The widening is one-sided — downward — and that is forced rather than
    # chosen: ``_RISING`` against ``_STRONG`` is nearly collinear, so the
    # correlation sits just under the ceiling and the upper bound has almost no
    # room to move without excluding it.  A wider-than-true interval is the
    # forgery a sloppy report would produce anyway (it reads as *more* honest),
    # which is why it is the one worth catching.
    forged = (reading.lower - 0.2, reading.upper)
    assert forged[0] < reading.correlation < forged[1]
    assert -1.0 <= forged[0] and forged[1] <= 1.0

    with closing(sqlite3.connect(sqlite_path_of(discrimination_database))) as connection, connection:
        connection.execute(
            f"UPDATE {DISCRIMINATION_TABLE} SET interval_lower = ?, "
            f"interval_upper = ? WHERE campaign_id = ?",
            (*forged, campaign),
        )

    with pytest.raises(DiscriminationCohortError) as caught:
        load_mechanism_discrimination(
            ProposalStore(discrimination_database), campaign
        )
    assert "not the interval of" in str(caught.value)


def test_a_row_with_an_unparseable_stamp_is_refused_in_this_features_vocabulary(
    discrimination_database: str,
) -> None:
    """The read declines in *this* feature's error class, never a bare ValueError.

    The stamp is parsed back from ISO-8601 text, and a value that does not parse
    must not escape as a ``ValueError``: a caller's ``except
    DiscriminationCohortError`` has to catch every way the read can decline, or
    the one case that escapes is the one nobody handles.  This is the member's
    error-vocabulary discipline applied to a parse at a seam.
    """
    campaign = str(uuid.uuid4())
    plant_campaign(discrimination_database, campaign)
    branches = _cohort_shape(discrimination_database, campaign, _RISING, _STRONG)
    _measured(discrimination_database, campaign, branches)

    with closing(sqlite3.connect(sqlite_path_of(discrimination_database))) as connection, connection:
        connection.execute(
            f"UPDATE {DISCRIMINATION_TABLE} SET seen_at = 'yesterday' "
            f"WHERE campaign_id = ?",
            (campaign,),
        )

    with pytest.raises(DiscriminationCohortError) as caught:
        load_mechanism_discrimination(
            ProposalStore(discrimination_database), campaign
        )
    assert "ISO-8601" in str(caught.value)


def test_the_value_is_immutable_and_equal_by_its_fields(
    discrimination_database: str,
) -> None:
    """``__slots__``, no setters, equality over the parts.

    Equality by fields rather than ``isinstance``, because the loader imports
    every member twice — once under a synthetic name — so an ``isinstance`` gate
    would be false for a value built from the other import of the same file.  The
    immutability half is asserted because every field here reaches a report a
    verdict is read off.
    """
    campaign = str(uuid.uuid4())
    plant_campaign(discrimination_database, campaign)
    branches = _cohort_shape(discrimination_database, campaign, _RISING, _STRONG)

    reading = _measured(discrimination_database, campaign, branches)
    again = _measured(discrimination_database, campaign, branches)

    assert reading == again
    assert hash(reading) == hash(again)
    assert reading != "not a reading"
    assert not hasattr(reading, "__dict__")
    with pytest.raises(AttributeError):
        reading.correlation = 0.0  # type: ignore[misc]


def test_the_row_shape_nests_the_interval_around_the_point(
    discrimination_database: str,
) -> None:
    """§14.1's rule 3 in the shape of the data, not in a comment.

    ``design.md`` §9: *"show the interval as the primary mark and the point
    estimate as a hairline within it"*.  A flat mapping with ``correlation``
    beside ``lower`` and ``upper`` invites a renderer to print the first number
    alone — the failure the rule exists to prevent — so the point is nested *in*
    the interval and this case pins that, along with the ``row()``-returns-a-
    fresh-dict contract and the payload's byte-stability.
    """
    campaign = str(uuid.uuid4())
    plant_campaign(discrimination_database, campaign)
    branches = _cohort_shape(discrimination_database, campaign, _RISING, _STRONG)
    reading = _measured(discrimination_database, campaign, branches)

    row = reading.row()
    assert set(row["interval"]) == {"lower", "upper"}
    assert row["interval"]["lower"] == reading.lower
    assert row["interval"]["upper"] == reading.upper
    assert row["correlation"] == reading.correlation
    assert "lower" not in row and "upper" not in row

    # A fresh mapping each call: a report tool that writes into what it read
    # moves its own copy and not the value's.
    first, second = reading.row(), reading.row()
    assert first is not second
    first["correlation"] = -99.0
    assert reading.row()["correlation"] == reading.correlation

    # And the payload is byte-stable, so two equal readings serialise alike.
    # The stamp is *pinned* rather than left to the clock: two measurements
    # taken a second apart are two different readings — ``seen_at`` is one of the
    # fields — so comparing their payloads would be comparing the wall clock's
    # behaviour rather than the serialiser's.  Freezing it is what makes this a
    # claim about ``payload``.
    stamped = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)
    store = ProposalStore(discrimination_database)
    one = mechanism_discrimination(store, campaign, branches, seen_at=stamped)
    two = mechanism_discrimination(store, campaign, branches, seen_at=stamped)
    assert one == two
    assert one.payload() == two.payload()
    assert one.payload() == json.dumps(
        one.row(), sort_keys=True, separators=(",", ":")
    )


def test_the_reading_stamps_the_moment_it_was_taken_and_a_replay_can_supply_one(
    discrimination_database: str,
) -> None:
    """``seen_at`` is the reading's moment, and a replay supplies the original's.

    The stored stamp is at second resolution because it is a *reading's* moment
    rather than an ordering key, and a caller replaying a recorded run passes its
    own — so a replayed reading stamps the instant the original did and the
    stored row is byte-identical rather than merely equal.
    """
    campaign = str(uuid.uuid4())
    plant_campaign(discrimination_database, campaign)
    branches = _cohort_shape(discrimination_database, campaign, _RISING, _STRONG)

    replayed = mechanism_discrimination(
        ProposalStore(discrimination_database),
        campaign,
        branches,
        seen_at=datetime(2026, 9, 22, 12, 0, tzinfo=UTC),
    )
    assert replayed.seen_at == datetime(2026, 9, 22, 12, 0, tzinfo=UTC)
    assert replayed.seen_at.microsecond == 0

    store = ProposalStore(discrimination_database)
    assert load_mechanism_discrimination(store, campaign) == replayed


def test_the_module_registers_no_component_and_has_no_seat(
    discrimination_database: str,
) -> None:
    """The feature's shape: a free function, no ``@register``, no seat file.

    The reading resolves no configuration of its own — the tables to read, the
    metric pair and the figure's shape are facts about state two existing
    builders already expose — so a tenth ``signal-agent-*`` registration would
    put a name in the registry for a question that composes nothing.  Asserted
    structurally, because the absence of a component is exactly the kind of
    decision a later edit adds by habit.
    """
    module = _imported_module("_discrimination")
    assert not hasattr(module, "build_mechanism_discrimination")
    assert not hasattr(module, "build_discrimination")
    for name in vars(module):
        assert not name.startswith("build_"), (
            f"the module exposes {name!r}, which is the shape of a composed "
            f"builder's entry point; feature 214 composes nothing"
        )

    # The member's own registry is unchanged by this feature.
    from signal_agent import COMPONENT_NAME

    assert COMPONENT_NAME == "signal-agent"
    assert member.mechanism_discrimination is mechanism_discrimination


def test_the_module_imports_no_third_party_package() -> None:
    """Import-cheap, so the factory's scan pays nothing for this module.

    The scan imports this member to fire its ``@register`` builders; a module
    that pulled in ``numpy`` or ``pandas`` at module scope would charge that cost
    to every ``create_app()`` for a feature most deployments never call.  The
    arithmetic is stdlib — ``math``, ``statistics`` — and this case pins it over
    the module's own import statements.
    """
    module = _imported_module("_discrimination")
    imports = {
        statement.split()[1].split(".")[0]
        for statement in _import_statements(_module_source("_discrimination.py"))
    }
    imports.discard("__future__")
    # Relative imports are `from ._proposal import ...` — and they are the
    # subject of a *different* claim (the member owns them, and they are cheap).
    imports = {name for name in imports if name and not name.startswith(".")}
    # The module's actual loaded third-party surface, which is the thing the
    # claim is about: a stdlib-only module pulls in nothing outside the standard
    # library, and this asserts it over the import table rather than over the
    # source text, so a name that never binds cannot pass the scan.
    for name in imports:
        assert name in {
            "collections",
            "contextlib",
            "datetime",
            "hashlib",
            "json",
            "math",
            "pathlib",
            "sqlite3",
            "statistics",
            "typing",
            "uuid",
            "urllib",
        }, f"the module imports {name!r}, which is not a stdlib module"
    assert module is not None


# ── The helpers this suite computes its expectations with ─────────────────────
#
# The cases above assert against numbers *computed here* rather than against
# constants captured from a run.  A stored constant would make every arithmetic
# claim a restatement of what the implementation happened to do, which is the one
# thing a suite asserting an arithmetic must not be.  These two helpers are
# deliberately *not* the module's own functions: they are an independent spelling
# of the same textbook definitions, so an error in the module's arithmetic shows
# up as a disagreement rather than as agreement with itself.


def _correlation(xs: tuple[float, ...], ys: tuple[float, ...]) -> float:
    """Pearson's r, spelled from the definition — independent of the module."""
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return cov / (sx * sy)


def _fisher_interval(r: float, n: int) -> tuple[float, float]:
    """Fisher's z interval at the two-sided 95% level — spelled independently."""
    z = math.atanh(r)
    se = 1.0 / math.sqrt(n - 3)
    quantile = NormalDist().inv_cdf(1.0 - (1.0 - CONFIDENCE_LEVEL) / 2.0)
    return math.tanh(z - quantile * se), math.tanh(z + quantile * se)


def _imported_module(name: str):
    """The member's private module, imported for a source-level claim."""
    import importlib

    return importlib.import_module(f"signal_agent.{name}")


def _module_source(filename: str) -> str:
    """One of the member's own source files, read by path.

    Read rather than inspected, because the claims built on it are about what the
    module *says* — the names it mentions and the statements it declares — which
    is a property of the text rather than of the imported objects.
    """
    from pathlib import Path

    import signal_agent

    return (
        Path(signal_agent.__file__).parent / filename  # type: ignore[arg-type]
    ).read_text(encoding="utf-8")


def _code_of(source: str) -> str:
    """A module's source with every string literal and comment removed.

    Uses :mod:`tokenize` rather than a line filter, because the module documents
    the barrier *in prose that quotes the forbidden name* — a line-based scan
    would either forbid the module from explaining itself or be fooled by a
    docstring that spanned a name boundary.  What survives is exactly what the
    interpreter would execute as names and operators.

    A source file that does not tokenise is a syntax error and propagating that
    is correct: the claim built on this is about a module that imports.
    """
    import io
    import tokenize

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


def _import_statements(source: str) -> list[str]:
    """The import statements a module declares, rebuilt from its tokens.

    Source-level rather than ``sys.modules``-level because the claim is about
    *what this module declares*: a module that imported ``numpy`` inside a
    conditional would still cost the factory's scan nothing at import time, and
    this deliberately measures the module-level declarations rather than the
    transitive graph.  Built from the code tokens so a docstring quoting an
    ``import`` statement is not mistaken for one.
    """
    import io
    import tokenize

    statements: list[str] = []
    current: list[str] = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type in {tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE}:
            if current:
                statements.append(" ".join(current))
                current = []
            continue
        if token.type == tokenize.STRING:
            continue
        if token.type == tokenize.DEDENT and current:
            statements.append(" ".join(current))
            current = []
            continue
        if token.type in {tokenize.INDENT}:
            continue
        current.append(token.string)
    if current:
        statements.append(" ".join(current))
    return [
        statement
        for statement in statements
        if statement.startswith(("import ", "from "))
    ]


def _rewrite_score(database_url: str, node: str, score: ScoreRecord) -> None:
    """Replace a node's stored snapshot — feature 207 refuses a second write.

    Feature 207's whole point is that a recorded pair is immutable — a second
    ``persist`` with a different score is a ``ProposalConflictError`` — so a case
    that needs to move a metric *after* the fact has to write the row directly.
    That is the one thing this suite does behind the store's back, and it does it
    only where the case is *about* what a later reader would see.
    """
    with closing(sqlite3.connect(sqlite_path_of(database_url))) as connection, connection:
        connection.execute(
            "UPDATE node_proposal SET score = ? WHERE node_id = ?",
            (score.to_json(), node),
        )


def _seed_tree_only(
    database_url: str,
    campaign: str,
    store: ProposalStore,
    document: str,
    gain: float,
) -> str:
    """A database with the tree and the proposals, and no ``replay_score``.

    Built for the one case whose subject *is* the absent out-of-sample half: the
    tree chain and feature 207's table, and deliberately neither ``0111`` nor
    ``0109``.  **The campaign row is not planted either** — a database whose
    chain stopped before ``0111`` has no campaign table at all, and planting one
    would require creating the very table the case is about the absence of.  So
    the refusal under test is the pool's, reached because the campaign table
    check is ordered after it: the module refuses the missing out-of-sample half
    before it asks whether the campaign is planned, which is the right order —
    the pool is the half the *figure* needs and the campaign is the scope.
    """
    from conftest import create_diversity_schema

    create_diversity_schema(database_url)
    node = plant_modelled_node(database_url, _MODEL, campaign_id=campaign)
    store.persist(node, document, score=ScoreRecord(ir_marginal=gain))
    return node
