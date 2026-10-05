"""Feature 215's suite: ``tree_diversity``, per campaign and per authoring model.

app_spec.xml, "Hypothesis Authoring Agent", feature 215: *System computes
tree_diversity as the count of distinct mechanism clusters per campaign, which
returns the figure per authoring model.*

The sentence is four claims and this file takes them one at a time, because they
fail in four different ways and a suite that tested "the feature" would let
three of them be true while the fourth was not:

* **computes tree_diversity as the count of distinct mechanism clusters** — the
  arithmetic, and *what a cluster is*.  The last half is the whole of the
  feature's difficulty: this member owns three candidate identities for "the
  same mechanism" and only one of them is this count's.  So the decision is
  pinned from both sides — two documents differing only in a numeric literal are
  **two** clusters (which is what fails if feature 210's skeleton was borrowed),
  and one document on two nodes is **one** cluster (which is what fails if the
  count is really a proposal count).
* **per campaign** — the scope.  Counted from the stored ``campaign_id``, never
  from the caller's pairing of node to campaign, and two campaigns' proposals
  never land in one another's figure.
* **which returns the figure per authoring model** — the stratification.  The
  answer is one figure per model, joined from ``node.agent_model_id``; the
  pooled number is **not** the answer, and the assertion that says so is the one
  that would pass on a scalar implementation that ignored the model entirely.
* **the barrier: the rationale is not a cluster key.**  Feature 211's column
  exists, its digest exists, and using either would produce a figure that looks
  like a measurement and is a function of what models say about themselves.  The
  refusal is **structural** — the module does not import ``_mechanism`` and its
  SQL selects two columns — so it is pinned structurally too, over the module's
  own source, rather than by behaviour a refactor could quietly change.

**The fixtures bring a real schema and a real writer.**  ``diversity_database``
runs five migrations by file path — ``0118``, ``0117``, ``0115``, ``0114``,
``0113`` — so the ``agent_model_id`` column every claim here groups by is the one
feature 100's revision adds, with that revision's own ``NOT NULL``.
And every proposal row is written by feature 207's own
:meth:`ProposalStore.persist`, so the history this feature counts is a history
the real store produced: nothing here hand-writes ``node_proposal``, and the one
place this suite *does* write a row by hand is the orphan case, which is
precisely the state feature 207 refuses to produce and therefore cannot be built
through it.
"""

from __future__ import annotations

import sqlite3
import sys
import uuid
from contextlib import closing

import pytest
import signal_agent as member
from conftest import (
    NODE_MIGRATION,
    TRIO_MIGRATION,
    create_schema,
    plant_modelled_node,
    plant_node,
    sqlite_path_of,
)
from signal_agent import (
    MODEL_COLUMN,
    NODE_PROPOSAL_NODE_COLUMN,
    NODE_PROPOSAL_TABLE,
    DiversityCohortError,
    ProposalHistoryStoreUnavailableError,
    ProposalNodeNotRecordedError,
    ProposalStore,
    TreeDiversity,
    tree_diversity,
)

#: Two model ids of the shape feature 203 pins — a provider/model/version
#: triple, not a rolling alias.  Spelled once at module scope because several
#: claims are *about the string itself* (the stratum keys are these values
#: verbatim) and a fixture that rebuilt them per test would make "the same
#: model" a claim about two constructions rather than about two strings.
_MODEL_A = "deepseek/deepseek-v4-flash/2026-09-10"
_MODEL_B = "openai/gpt-5.6-sol/2026-08-01"

#: Two genuinely different mechanisms, and two that differ **only in a numeric
#: literal**.  The second pair is the load-bearing one: it is what a
#: skeleton-based count would merge and this feature's count must not.  Spelled
#: as source text because the document *is* the artefact — feature 207 stores it
#: verbatim and identifies it by the hash of exactly these bytes.
_MOMENTUM = "def signal(ctx, seed):\n    return ctx.close.rolling_mean(20)\n"
_REVERSION = "def signal(ctx, seed):\n    return -ctx.open.rolling_mean(5)\n"
_TWEAKED = "def signal(ctx, seed):\n    return ctx.close.rolling_mean(21)\n"
_CARRIED_ON = "def signal(ctx, seed):\n    return ctx.close.ewm_mean(20)\n"


def _campaign() -> str:
    """A fresh campaign id — the scope every test names explicitly.

    A function rather than a constant, because two tests sharing one id would
    make "the figure is scoped to this campaign" a claim about the suite's
    bookkeeping rather than about the count.  The capability under test is that
    the *stored* campaign decides the scope, and each case wants its own.
    """
    return str(uuid.uuid4())


def _record(
    database_url: str,
    campaign_id: str,
    model: str,
    document: str,
    *,
    mechanism: str | None = None,
) -> str:
    """Plant a node carrying ``model`` and record ``document`` against it.

    The one construction every claim below is built from, and it goes through
    **feature 207's own writer** rather than an ``INSERT``: the rows feature 215
    counts are then rows the real store produced, and a change to what that
    store records shows up here as a change in the figure rather than passing
    unnoticed behind this suite's own SQL.

    **The stored ``code_hash`` is always the store's own, never this suite's.**
    That is deliberate and it is what makes the two halves of the cluster
    identity separable: identical documents collide on their derived hash (one
    cluster), and different documents do not (two).  A suite that wrote hashes
    by hand could assert that a shared hash is one cluster while the *store* —
    the thing a running campaign actually calls — shared them differently.

    ``mechanism`` exists for the barrier's behavioural half: a test that plants
    the *same* rationale on two nodes and asserts they are still two clusters.
    """
    node = plant_modelled_node(
        database_url,
        model,
        campaign_id=campaign_id,
        stated_mechanism=mechanism,
    )
    # The store is constructed *after* the node is planted but creates its table
    # only on its first connection, which is ``persist`` below — so the fixture's
    # tree is a tree feature 207 has not written to yet, and the absent-table
    # case is a database where that never happened.
    ProposalStore(database_url).persist(node, document)
    return node


# ── The arithmetic, and what a cluster is ─────────────────────────────────────


def test_the_figure_is_distinct_mechanisms_per_campaign_and_per_model(
    diversity_database: str,
) -> None:
    """The sentence, whole: three clusters over four proposals, split by model.

    Model A writes two documents (two clusters); model B writes one document on
    two nodes (one cluster over two proposals).  The pooled distinct count is
    therefore two and *neither* stratum's count is that number — which is the
    reading that fails on an implementation returning a scalar.
    """
    campaign = _campaign()
    _record(diversity_database, campaign, _MODEL_A, _MOMENTUM)
    _record(diversity_database, campaign, _MODEL_A, _REVERSION)
    _record(diversity_database, campaign, _MODEL_B, _CARRIED_ON)
    _record(diversity_database, campaign, _MODEL_B, _CARRIED_ON)

    figure = tree_diversity(ProposalStore(diversity_database), campaign)

    assert figure.by_model[_MODEL_A] == 2
    assert figure.by_model[_MODEL_B] == 1
    assert figure.proposals == 4
    # The pooled number is deliberately not offered, and this is the assertion
    # that says so rather than merely leaving the method absent: the two strata
    # sum to 3, the pooled *distinct* count is 2, and an implementation that
    # reported either as "the figure" would be answering a different question.
    assert sum(figure.by_model.values()) == 3
    assert len(set(figure.by_model.values())) == 2


def test_a_cluster_is_the_document_not_its_constants_erased(
    diversity_database: str,
) -> None:
    """Two proposals differing **only in a numeric literal** are two clusters.

    **This is the test that pins what a cluster is.**  Feature 210's
    :func:`proposal_skeleton` erases numeric literals, so a count built on
    :func:`skeleton_digest` would merge these two documents into one cluster —
    and the docs' own word for the tree is exactly what that would hide: forty
    structurally distinct variants of one indicator, each fitting noise, is the
    failure §14.1 measures, and a skeleton-erased count reports it as forty
    clusters.  ``code_hash`` reports what was written.
    """
    campaign = _campaign()
    _record(diversity_database, campaign, _MODEL_A, _MOMENTUM)
    _record(diversity_database, campaign, _MODEL_A, _TWEAKED)

    figure = tree_diversity(ProposalStore(diversity_database), campaign)

    assert figure.by_model[_MODEL_A] == 2, (
        "a tweaked constant is still a distinct proposal document; if this "
        "reads 1, the cluster identity has silently become feature 210's "
        "numeric-erased skeleton"
    )
    assert figure.proposals == 2


def test_one_document_on_two_nodes_is_one_cluster(
    diversity_database: str,
) -> None:
    """Two nodes carrying the same document are one cluster over two proposals.

    The other half of the cluster identity, and the half that makes the figure
    *diversity* rather than *activity*: a plan that grew by re-proposing what it
    already held shows a count that does not move — §14.1's *"diversity is
    precisely what roots need"* read as an arithmetic property.

    The denominator is what keeps this honest: ``proposals == 2`` beside
    ``clusters == 1`` is the reading, and a value object that hid the cohort
    would make this indistinguishable from a campaign that proposed once.
    """
    campaign = _campaign()
    _record(diversity_database, campaign, _MODEL_A, _MOMENTUM)
    _record(diversity_database, campaign, _MODEL_A, _MOMENTUM)

    figure = tree_diversity(ProposalStore(diversity_database), campaign)

    assert figure.by_model[_MODEL_A] == 1
    assert figure.proposals == 2


def test_the_figure_is_scoped_to_the_campaign_named(diversity_database: str) -> None:
    """One campaign's proposals never appear in another's figure.

    Scoped by the stored ``campaign_id`` — read off the ``node`` row by feature
    207 at write time, never taken from this caller — so the scope is §9's
    *"one campaign = one discovery tree"* rather than a claim about the
    arguments.  Two campaigns with *identical* proposals are the case that
    catches a count that ignored the scope: the pooled reading would be one
    cluster, the correct scoped reading is one cluster each.
    """
    first, second = _campaign(), _campaign()
    _record(diversity_database, first, _MODEL_A, _MOMENTUM)
    _record(diversity_database, second, _MODEL_A, _MOMENTUM)

    figure = tree_diversity(ProposalStore(diversity_database), first)

    assert figure.campaign_id == first
    assert figure.by_model[_MODEL_A] == 1
    assert figure.proposals == 1, (
        "the other campaign's proposal was counted; the scope is the stored "
        "campaign_id, not the caller's arguments"
    )


def test_a_campaign_with_no_proposals_answers_zero(diversity_database: str) -> None:
    """No recorded proposals is zero clusters — a real value, not a refusal.

    A campaign that has not proposed yet is feature 207's own documented state,
    and refusing it would make the first call of every campaign an error.  The
    answer is a genuine :class:`TreeDiversity` with an empty stratification and
    a zero denominator, which is what a report prints for a fresh campaign.

    The distinction this shares with the absent-*table* case below is the whole
    of the pair: **a deployment with a history and a campaign without proposals
    is zero; a deployment without a history is not a number at all.**  So the
    store here is one that has recorded — the neighbouring campaign's proposal
    is what makes it so — and the campaign asked about is a fresh one.
    """
    asker = _campaign()
    _record(diversity_database, asker, _MODEL_A, _MOMENTUM)

    figure = tree_diversity(ProposalStore(diversity_database), _campaign())

    assert isinstance(figure, TreeDiversity)
    assert figure.by_model == {}
    assert figure.proposals == 0
    # And the recorded campaign still answers, so this is not a store that
    # answered zero because it holds nothing.
    assert tree_diversity(ProposalStore(diversity_database), asker).proposals == 1


# ── The barrier: the rationale is never the cluster key ───────────────────────


def test_the_same_rationale_on_two_documents_is_still_two_clusters(
    diversity_database: str,
) -> None:
    """Identical ``stated_mechanism``, different source: **two** clusters.

    The behavioural half of the barrier.  Feature 211's column holds the
    agent's prose and feature 210's docstring records why it fails as a
    diversity key anyway — *"a weak model asked for the 400th variant states it
    confidently in fresh prose, so the claim differs while the structure
    repeats"* — and the converse is just as true: one rationale covering two
    genuinely different documents is two mechanisms, not one.
    """
    campaign = _campaign()
    shared = "Cross-sectional momentum after a liquidity shock."
    _record(
        diversity_database,
        campaign,
        _MODEL_A,
        _MOMENTUM,
        mechanism=shared,
    )
    _record(
        diversity_database,
        campaign,
        _MODEL_A,
        _REVERSION,
        mechanism=shared,
    )

    figure = tree_diversity(ProposalStore(diversity_database), campaign)

    assert figure.by_model[_MODEL_A] == 2, (
        "two different documents under one rationale were merged; the cluster "
        "key has become the agent's stated claim"
    )


def test_the_module_never_reads_the_stated_mechanism_column() -> None:
    """The barrier is structural: the column is not imported, not selected.

    A refusal enforced by a check is a refusal a later edit can move; a refusal
    enforced by *what the code can reach* is not.  So this claim is made over
    the module rather than over its behaviour, in two layers:

    * **what the SQL names** — the statement constants, which are what actually
      runs against the database.  A column that is not selected cannot reach the
      figure, whatever the module's prose says, and this is the layer a
      refactor cannot quietly move.
    * **what the module imports** — read from the module's own namespace rather
      than from its source text, because this module's docstrings *do* name
      feature 211 and feature 210 in order to explain why neither is used, and a
      substring sweep of the source cannot tell an explanation from a call.  The
      namespace can: no submodule of the member whose name is not this one's.

    Both layers are asserted because either alone is satisfiable while the other
    fails: an implementation could import the digest and never call it, or could
    spell the column as a literal in its SQL while importing nothing.
    """
    module = member._diversity  # the subject of the claim, private or not
    sql = "\n".join(
        value
        for name, value in vars(module).items()
        if name.endswith("_SQL") and isinstance(value, str)
    )

    assert "stated_mechanism" not in sql, (
        "feature 215's SQL names feature 211's column; the rationale is "
        "`dedup + human review ONLY` per §9.1, and 211's own barrier names this "
        "feature's `agent_model_id` stratification as what a "
        "rationale-conditioned figure would corrupt"
    )
    assert "mechanism" not in sql.replace("_mechanism", ""), (
        "feature 215's SQL reaches for a mechanism digest; a digest of the "
        "agent's stated claim is not a cluster key"
    )
    assert "skeleton" not in sql, (
        "feature 215 must not borrow feature 210's structure key — that count "
        "is 210's own, and its module assigns the diversity figure elsewhere"
    )

    # The import layer: which *member* submodules this module pulled in.  Read
    # off the module object rather than from its source text, so an unused
    # import (the standing temptation) is caught as surely as a used one — and
    # filtered to the member's own package, because ``sqlite3`` and ``uuid`` are
    # the standard library reaching the database directly, which is the point of
    # the module rather than a borrowing of anyone's law.
    package = module.__name__.rsplit(".", 1)[0]
    imported = {
        name
        for name, value in vars(module).items()
        if isinstance(value, type(sys))  # a module object, however imported
        and value.__name__.startswith(package + ".")
    }
    assert imported == set(), (
        f"feature 215 imports {sorted(imported)}; it reads the database "
        f"directly and must borrow no sibling member's law — least of all "
        f"feature 211's or feature 210's, whose keys are the wrong cluster "
        f"identities for this count"
    )

    # And the positive half: the columns the count actually turns on.
    assert MODEL_COLUMN in sql
    assert NODE_PROPOSAL_TABLE in sql
    assert NODE_PROPOSAL_NODE_COLUMN in sql


def test_no_null_branch_filter_is_applied(diversity_database: str) -> None:
    """Every recorded proposal is counted; nothing is filtered out as null.

    §14.1's two lines are asymmetric and the asymmetry is deliberate:
    ``mechanism_discrimination = corr(IS_gain, OOS_gain | real branches)``
    carries the ``| real branches`` qualifier and ``tree_diversity = distinct
    mechanism clusters per campaign`` does not.  The corroborating facts are
    that the real/null discriminant lives where the evaluation ran —
    ``is_null`` is *"absent from the tree store entirely"* per app_spec 447 and
    *"never ... returns is_null in any form"* per 456 — and ``node_proposal``
    records no such flag.  So there is nothing to filter *on*, and a later
    reader who notices the asymmetry should find it already answered rather
    than find a filter invented to restore a symmetry the spec does not have.

    Asserted two ways, because the two could come apart: no statement mentions
    a null discriminant, and a tree that carries all the rows the fixture
    planted is counted in full.
    """
    sql = "\n".join(
        value
        for name, value in vars(member._diversity).items()
        if name.endswith("_SQL") and isinstance(value, str)
    )
    for token in ("is_null", "real_branch", "IS NULL AND", "real_only"):
        assert token not in sql, (
            f"feature 215's SQL carries {token!r}; the `| real branches` "
            f"qualifier is on feature 214's line, not this one"
        )
    # ``IS NULL`` does appear, in exactly one place and for a different reason:
    # the unmodelled sweep refuses a node with no authoring model.  That is a
    # guard on the *stratum*, not a filter on the branch — so it is required to
    # be there, and required to be the only occurrence.
    assert sql.count("IS NULL") == 1, (
        "expected one IS NULL, the unmodelled node guard; found "
        f"{sql.count('IS NULL')} — a second one is a branch filter this "
        f"feature does not have"
    )

    campaign = _campaign()
    _record(diversity_database, campaign, _MODEL_A, _MOMENTUM)
    _record(diversity_database, campaign, _MODEL_A, _REVERSION)
    _record(diversity_database, campaign, _MODEL_B, _CARRIED_ON)

    figure = tree_diversity(ProposalStore(diversity_database), campaign)

    assert figure.proposals == 3, "a row was filtered out; nothing may be"
    assert figure.by_model == {_MODEL_A: 2, _MODEL_B: 1}


def test_the_module_has_no_write_path() -> None:
    """The figure is a measurement: nothing here writes.

    §14.1's sentence for this feature is *"computes ... which returns the
    figure"* while feature 214's is *"persists"*, so a write in this module
    would be building the wrong feature.  Read-only is also what makes the
    reading repeatable — taking a diversity figure can never change the figure
    the next reading reports.

    **Asserted over the SQL, not over the prose**, and the distinction is not
    pedantic: this module's docstrings do discuss the joins a write would need,
    so a sweep of the raw source finds ``UPDATE`` in an English sentence and
    fails a correct module.  What can actually run is the set of module-level
    statement constants, so that is what is read — each one is required to be a
    ``SELECT`` or a ``PRAGMA``, which is a positive form a future edit has to
    argue with rather than a list of forbidden words it can slip past.
    """
    statements = {
        name: value
        for name, value in vars(member._diversity).items()
        if name.endswith("_SQL") and isinstance(value, str)
    }
    assert len(statements) >= 5, (
        f"expected the module's statement constants, found {sorted(statements)}"
    )
    for name, statement in statements.items():
        opening = statement.strip().split()[0].upper()
        assert opening in {"SELECT", "PRAGMA"}, (
            f"{name} opens with {opening}; feature 215 is a reader, and a "
            f"writer in this module would be building feature 214's half"
        )
        # The positive form above admits a compound statement's *second* half,
        # so the write verbs are still refused here — by word, but only inside
        # SQL that can run.
        for verb in ("INSERT ", "UPDATE ", "DELETE ", "DROP ", "CREATE "):
            assert verb not in statement.upper(), f"{name} emits {verb.strip()}"
    # ``CREATE`` above also covers 207's own schema string, which this module
    # deliberately does not restate: the table is created by the store that owns
    # it, and a second spelling here would be a second owner.


# ── The refusals ──────────────────────────────────────────────────────────────


def test_a_database_with_no_recorded_history_is_refused(
    diversity_database_url: str,
) -> None:
    """No ``node_proposal`` table is a refusal — and emphatically not a zero.

    The distinction feature 186's census draws for its own absent table, drawn
    here in the same direction and for a sharper reason: a zero answered about a
    database with no history in it is a figure this member *invented*, and it is
    indistinguishable from the flattering reading *this model wrote one
    mechanism*.  So the absent table raises rather than answering.
    """
    store = ProposalStore(diversity_database_url)

    with pytest.raises(ProposalHistoryStoreUnavailableError) as refusal:
        tree_diversity(store, _campaign())

    assert NODE_PROPOSAL_TABLE in str(refusal.value)
    assert "211" not in str(refusal.value), (
        "the refusal must name feature 207's table, not another feature's"
    )


def test_an_object_that_is_not_the_history_law_is_refused_before_any_read(
    diversity_database: str,
) -> None:
    """A handle with no ``history`` verb is refused naming the *shape*.

    The seam is duck-typed — an ``isinstance`` gate would refuse the store the
    module loader re-executes under a synthetic name — so the two names it uses
    are what is checked: a callable ``history`` and a ``path``.  The assertion
    that matters is that the refusal names the shape rather than the file: a
    validation that had already opened a database would be one that ran too
    late.
    """
    with pytest.raises(DiversityCohortError) as refusal:
        tree_diversity(
            {"path": sqlite_path_of(diversity_database)}, _campaign()
        )

    assert "history" in str(refusal.value)
    assert "215" in str(refusal.value)
    # The point of the ordering: nothing was opened, so the refusal could not
    # have come from the disk.
    assert "sqlite" not in str(refusal.value).lower()


def test_a_handle_with_no_path_is_refused(diversity_database: str) -> None:
    """A handle that fronts the verb but names no database is refused too."""

    class _Verbless:
        def history(self, campaign_id: object) -> tuple[()]:  # pragma: no cover
            return ()

    with pytest.raises(DiversityCohortError) as refusal:
        tree_diversity(_Verbless(), _campaign())

    assert "path" in str(refusal.value)


def test_a_campaign_id_that_is_not_a_uuid_is_refused(diversity_database: str) -> None:
    """The scope is UUID text, canonicalised rather than trusted.

    ``node_proposal.campaign_id`` is UUID text, so an id that cannot join it
    would silently count another campaign's proposals as this one's — the
    failure the canonical form exists to prevent.
    """
    _record(diversity_database, _campaign(), _MODEL_A, _MOMENTUM)
    store = ProposalStore(diversity_database)

    with pytest.raises(DiversityCohortError) as refusal:
        tree_diversity(store, "momentum-campaign")

    assert "campaign" in str(refusal.value).lower()


def test_a_tree_without_the_model_column_is_refused(
    diversity_database_url: str,
) -> None:
    """A tree that has not reached ``0115`` cannot answer a *per-model* figure.

    The one refusal that has no flat fallback: feature 215's sentence is
    *"returns the figure per authoring model"*, so a tree with no
    ``agent_model_id`` cannot answer the question at all — and reporting one
    number in its place would be a stratum this member invented.  The refusal
    names the revision, because that is its whole actionable content.

    The tree is built the only honest way to reach that state: ``0118`` for the
    table, 207's own store for its own lazily-created table, and ``0115`` never
    applied.  Running 0115 and then dropping the column would be testing
    SQLite's ``DROP COLUMN``; this is a deployment that has not taken the
    migration, which is what the refusal is about.
    """
    create_schema(diversity_database_url, NODE_MIGRATION, TRIO_MIGRATION)
    campaign = _campaign()
    store = ProposalStore(diversity_database_url)
    node = plant_node(diversity_database_url, campaign_id=campaign)
    store.persist(node, _MOMENTUM)

    with pytest.raises(DiversityCohortError) as refusal:
        tree_diversity(ProposalStore(diversity_database_url), campaign)

    assert "0115" in str(refusal.value)
    assert "model" in str(refusal.value).lower()


def test_a_tree_with_no_node_table_is_refused(diversity_database_url: str) -> None:
    """A database with no tree cannot be grouped by anything on it.

    Raised as feature 207's own :class:`ProposalNodeNotRecordedError` — the
    class whose docstring already covers *"the database holds no ``node`` table
    at all, naming 0118"* — rather than as a new class here.  That is the
    member's discipline: a class buys a *repair* a caller can act on, and this
    repair is the one 207 already names.

    The history table is 207's real one rather than a stub, because the refusal
    has to be *about the tree*: the store creates its own table on its first
    connection (207's ``_connect``), so the database reaching the count holds a
    real ``node_proposal`` and no ``node`` — the state after a tree has been
    dropped from under a recorded history, which is the only way a database gets
    here at all.
    """
    create_schema(diversity_database_url, NODE_MIGRATION, TRIO_MIGRATION)
    store = ProposalStore(diversity_database_url)
    store.persist(plant_node(diversity_database_url), _MOMENTUM)
    with (
        closing(sqlite3.connect(sqlite_path_of(diversity_database_url))) as connection,
        connection,
    ):
        connection.execute("DROP TABLE node")

    with pytest.raises(ProposalNodeNotRecordedError) as refusal:
        tree_diversity(store, _campaign())

    assert "0118" in str(refusal.value)


def test_a_proposal_whose_node_is_gone_is_refused(diversity_database: str) -> None:
    """An orphan row is refused, *before* the join that would have dropped it.

    Feature 207 refuses this state at write time, so a row here is a database
    that has lost a node.  The count's grouped read is an inner join, and an
    orphan is exactly the row an inner join drops silently — which is the one
    direction a count must never move by accident, because it understates the
    figure for precisely the model whose nodes went missing.

    The row is written by hand because it is the state the real writer cannot
    produce; that is the point of the case.
    """
    campaign = _campaign()
    _record(diversity_database, campaign, _MODEL_A, _MOMENTUM)
    orphan = str(uuid.uuid4())
    with (
        closing(sqlite3.connect(sqlite_path_of(diversity_database))) as connection,
        connection,
    ):
        connection.execute(
            f"INSERT INTO {NODE_PROPOSAL_TABLE} (node_id, campaign_id, proposal, "
            f"code_hash, score, generated_at, recorded_at) "
            f"VALUES (?, ?, ?, ?, ?, ?, ?)",
            (orphan, campaign, _REVERSION, "b" * 64, "{}", "2026-01-01", "2026-01-01"),
        )

    with pytest.raises(ProposalNodeNotRecordedError) as refusal:
        tree_diversity(ProposalStore(diversity_database), campaign)

    assert orphan in str(refusal.value), (
        "the refusal must name the node, so an operator can find the row"
    )


def test_a_node_with_no_authoring_model_is_refused_not_bucketed(
    diversity_database: str,
) -> None:
    """A NULL or blank model is a refusal, not an ``""`` stratum.

    ``0115`` declares the column ``NOT NULL``, so this is a brought-forward or
    hand-edited database — and a bucket labelled "unknown" would print beside
    the real strata in §14.1's table as though it were a model, making the
    comparison uninterpretable rather than merely incomplete.  The whitespace
    case is included because a writer that supplied ``"  "`` passes a bare
    ``IS NULL`` test and lands in a stratum no model answers to.
    """
    campaign = _campaign()
    _record(diversity_database, campaign, _MODEL_A, _MOMENTUM)
    blank = plant_modelled_node(
        diversity_database, " ", campaign_id=campaign
    )
    with (
        closing(sqlite3.connect(sqlite_path_of(diversity_database))) as connection,
        connection,
    ):
        connection.execute(
            f"INSERT INTO {NODE_PROPOSAL_TABLE} (node_id, campaign_id, proposal, "
            f"code_hash, score, generated_at, recorded_at) "
            f"VALUES (?, ?, ?, ?, ?, ?, ?)",
            (blank, campaign, _REVERSION, "c" * 64, "{}", "2026-01-01", "2026-01-01"),
        )

    with pytest.raises(DiversityCohortError) as refusal:
        tree_diversity(ProposalStore(diversity_database), campaign)

    assert blank in str(refusal.value)


# ── The value object ──────────────────────────────────────────────────────────


def test_the_figure_carries_its_scope_and_its_denominator(
    diversity_database: str,
) -> None:
    """The three fields, and the row §14.1's report writes.

    Rule 2 of §14.1's reporting rules — *"both trivial baselines appear in every
    table"* — read as a structural requirement: a cluster count without its
    denominator is uninterpretable, and the degenerate baseline for a diversity
    count is the floor of one.  The denominator is therefore a field rather than
    something a report has to go and find.
    """
    campaign = _campaign()
    _record(diversity_database, campaign, _MODEL_A, _MOMENTUM)
    _record(diversity_database, campaign, _MODEL_B, _REVERSION)
    _record(diversity_database, campaign, _MODEL_B, _REVERSION)

    figure = tree_diversity(ProposalStore(diversity_database), campaign)

    assert figure.campaign_id == campaign
    assert figure.proposals == 3
    row = figure.row()
    assert row["campaign_id"] == campaign
    assert row["proposals"] == 3
    assert row["by_model"] == {_MODEL_A: 1, _MODEL_B: 1}
    # A fresh dict per call, so a report tool writing into what it read moves
    # its own copy rather than the figure.
    assert figure.row() is not row
    assert figure.row() == row
    # And the mapping itself refuses writes: "the figure per model" is a
    # reading, not a scratchpad.
    with pytest.raises(TypeError):
        figure.by_model[_MODEL_A] = 99  # type: ignore[index]


def test_the_denominator_cannot_be_shadowed_by_a_model_named_for_it(
    diversity_database: str,
) -> None:
    """A model literally named ``proposals`` cannot overwrite the denominator.

    The reason :meth:`TreeDiversity.row` nests ``by_model`` rather than
    spreading it: the model keys are values *from the database*, and feature
    203's column takes whatever a deployment pins.  A flat row would let one
    collision silently replace the cohort size — the number rule 2 exists to
    keep beside the figure.
    """
    campaign = _campaign()
    _record(diversity_database, campaign, "proposals", _MOMENTUM)

    figure = tree_diversity(ProposalStore(diversity_database), campaign)
    row = figure.row()

    assert row["proposals"] == 1
    assert row["by_model"] == {"proposals": 1}


def test_the_value_refuses_shapes_no_read_could_produce() -> None:
    """The constructor's invariants, one refusal at a time.

    A hand-built figure is a test's prerogative, and every field here reaches a
    report that compares models against one another, so a value no read could
    produce is refused rather than printed.  ``bool`` is refused *first* among
    the numeric checks, because ``True`` is ``1`` in Python and a flag where a
    count belongs would report a model that wrote one mechanism.
    """
    campaign = _campaign()

    with pytest.raises(DiversityCohortError):
        TreeDiversity(campaign_id=campaign, by_model={_MODEL_A: True}, proposals=1)

    with pytest.raises(DiversityCohortError):
        TreeDiversity(campaign_id=campaign, by_model={_MODEL_A: -1}, proposals=1)

    with pytest.raises(DiversityCohortError):
        TreeDiversity(campaign_id=campaign, by_model={_MODEL_A: 1.0}, proposals=1)

    with pytest.raises(DiversityCohortError):
        TreeDiversity(campaign_id=campaign, by_model={"": 1}, proposals=1)

    with pytest.raises(DiversityCohortError):
        TreeDiversity(campaign_id=campaign, by_model={_MODEL_A: 1}, proposals=-1)

    with pytest.raises(DiversityCohortError):
        TreeDiversity(campaign_id=campaign, by_model={_MODEL_A: 1}, proposals=True)

    with pytest.raises(DiversityCohortError):
        TreeDiversity(campaign_id="not-a-uuid", by_model={_MODEL_A: 1}, proposals=1)

    with pytest.raises(DiversityCohortError):
        TreeDiversity(campaign_id=campaign, by_model=[(_MODEL_A, 1)], proposals=1)  # type: ignore[arg-type]


def test_a_cluster_count_larger_than_its_cohort_is_refused() -> None:
    """The one invariant feature 186's census has no analogue for.

    Each model wrote a *share* of the campaign's proposals, so no stratum can
    hold more clusters than the campaign holds documents.  A count larger than
    its denominator is exactly what a fanned-out join produces — a duplicate
    ``node.id``, a second row per node — and reporting it would put a figure
    from no tree into §14.1's M2 comparison.
    """
    campaign = _campaign()

    with pytest.raises(DiversityCohortError) as refusal:
        TreeDiversity(campaign_id=campaign, by_model={_MODEL_A: 5}, proposals=2)

    assert _MODEL_A in str(refusal.value)
    # The equal case is admitted, and that is the boundary worth pinning: a
    # campaign where one model wrote every proposal has one cluster per
    # proposal, so the equality is a real reading rather than an edge case.
    figure = TreeDiversity(campaign_id=campaign, by_model={_MODEL_A: 2}, proposals=2)
    assert figure.by_model[_MODEL_A] == 2


def test_the_value_is_frozen_and_compares_by_all_three_fields() -> None:
    """Equal readings are equal values; different scopes are different figures."""
    campaign = _campaign()
    other = _campaign()
    first = TreeDiversity(
        campaign_id=campaign, by_model={_MODEL_A: 2, _MODEL_B: 1}, proposals=4
    )
    same = TreeDiversity(
        campaign_id=campaign, by_model={_MODEL_B: 1, _MODEL_A: 2}, proposals=4
    )
    elsewhere = TreeDiversity(
        campaign_id=other, by_model={_MODEL_A: 2, _MODEL_B: 1}, proposals=4
    )

    assert first == same, "insertion order must not make two readings unequal"
    assert hash(first) == hash(same)
    assert first != elsewhere, "two campaigns' figures are two figures"
    assert first != "not a figure"
    assert {first, same} == {first}, "a reading is usable as a set member"


def test_a_campaign_id_is_canonicalised_across_spellings(
    diversity_database: str,
) -> None:
    """One campaign in two casings is one campaign.

    ``node_proposal.campaign_id`` is TEXT holding UUID text, so a mixed-case
    spelling would make one campaign look like two — here, in the question of
    which proposals are counted together.  The same normalisation feature 207
    applies to the column this read is scoped by.
    """
    campaign = _campaign()
    _record(diversity_database, campaign, _MODEL_A, _MOMENTUM)
    store = ProposalStore(diversity_database)

    figure = tree_diversity(store, campaign.upper())

    assert figure.campaign_id == campaign
    assert figure.proposals == 1


# ── The shape of the feature: no component, no seat ───────────────────────────


def test_the_feature_registers_no_component_and_no_seat() -> None:
    """Feature 215 composes nothing — asserted, so a later feature cannot slip one in.

    The count resolves no configuration of its own: the table to read, the
    column to join and the figure's shape are all facts about state the existing
    builders already expose, so there is nothing for a component to *build*.
    It is a free function reached from the member, the way feature 186's
    ``world_census`` sits beside the bootstrap pool.

    The hazard this guards is not hypothetical in this member: ``Registration``
    is keyed by name, so a tenth builder taking a ``signal-agent-*`` name would
    sit silently beside the nine that exist — and one taking a name that sorts
    into the middle would break the contiguity ``test_component.py`` pins for
    the ordering law (feature 123).  So the assertion is on the *count* of the
    member's names, not merely on the absence of one spelling: a new component
    here is a decision this suite should have to be edited to allow.
    """
    from app.module_loader import create_app

    application = create_app()
    registered = sorted(
        name for name in application.order if name.split("-", 2)[:2] == ["signal", "agent"]
    )

    assert "diversity" not in " ".join(registered), (
        f"feature 215 composes nothing; found {registered}"
    )
    assert len(registered) == len(set(registered))
    # The member still answers the feature from its package rather than from the
    # application: ``tree_diversity`` is imported by ``__init__.py``, reachable
    # as ``from signal_agent import tree_diversity`` exactly as feature 186's
    # ``world_census`` is, and no component handle is involved.
    assert callable(member.tree_diversity)
    # And feature 215 contributes no name to the registry.  A builder
    # registering under a name no module-level constant declares would be
    # invisible to a constant-by-constant check, so this is asserted over the
    # composed application instead: every registered name is one of the
    # member's declared component names, and the count is the count.
    declared = {
        value
        for name, value in vars(member).items()
        if name.endswith("_COMPONENT_NAME") and isinstance(value, str)
    }
    assert len(declared) == 9, (
        f"the member declares {len(declared)} prefixed component names; the "
        f"Authoring Foundation's author (additions_spec_llm_authoring.xml, "
        f"feature 8) added the ninth under 'signal-author' — a name the "
        f"prefix filter above does not count, deliberately, because it is a "
        f"new category's seat rather than a tenth law in this one — and a "
        f"tenth arrives only if this suite is edited to say so: "
        f"{sorted(declared)}"
    )
    # ``signal-agent`` itself is the member's own law and the prefixed names
    # that share its prefix are the features that compose on top of it, so
    # the composed application's surface is exactly those.  Both terms use
    # the prefix filter, because the Authoring Foundation's ``signal-author``
    # is a declared name of a *new category's* seat rather than a law in this
    # one — it belongs to the count above and to neither side of this
    # equality.  A tenth law from a later feature would appear in
    # ``registered`` and in neither term of this equality.
    assert registered == sorted(
        name
        for name in declared | {member.COMPONENT_NAME}
        if name.split("-", 2)[:2] == ["signal", "agent"]
    )
