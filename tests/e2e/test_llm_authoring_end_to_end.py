"""End-to-end: one LLM-authored refinement, verified with no network.

The LLM-authoring addition (``additions_spec_llm_authoring.xml``) built the
authoring path as members' worth of pieces — pinned models and a rotating
frontier tier (providers features 2–4), the C3 prompt and the answer's parse
(signal-agent features 5–6), the author itself (feature 7) and the offline
policy reviser (feature 9, dreaming).  Every piece has a member suite, and a
member suite proves a module's behaviour, not that the assembled pieces reach
one another.  This journey is that wiring check, and it is the addition's own
headline sentence: *the system verifies one LLM-authored refinement end to
end, with no network.*

**The journey.**  A campaign with one root node row (depth 0) is seeded in a
throwaway SQLite database, together with a prior proposal in the
``ProposalHistoryStore``.  An ``LLMSignalAuthor`` is built over a
``providers.AuthoringSession`` whose resolver answers ``RecordedProvider``
fixtures; ``discovery.NodeExpansion(author, database_url)`` expands the root
and answers a ``RefinedSignal`` carrying the authored code and the stated
mechanism.  The attempt is persisted with an ``AttemptProvenance`` built from
``record.attempt_provenance_terms()``, ``record_authoring(record)`` files the
authoring provenance, and the proposal is stored with
``ProposalHistoryStore.persist``.  A second expansion at depth 2 uses the
depth pin, ``record_campaign_cache_rate`` persists the campaign's measured
rate, and an ``LLMReviser`` revises an incumbent through ``revise_policy``.
A refusal path is covered too: a fixture answer with no python block, retried
once, raises ``AuthoringRefusedError``.

**No socket, no credential, anywhere in this file.**  The model calls are
answered twice over the same script.  The *capture* pass runs the whole
choreography against a scripted ``Provider`` subclass (a fake the base class
validates like any backend) wrapped in ``RecordingProvider``, and files every
exchange with ``FixtureStore`` — the same record-then-replay seam the
live-providers addition ships.  The *replay* pass runs the identical
choreography over a fresh, identically seeded database with the resolver
answering ``RecordedProvider`` — a backend that has no transport to fall back
on — and every assertion below reads the replay's rows.  Nothing here imports
a live backend, names an environment variable or holds a key-shaped string:
the fixture files under ``tmp_path`` are the only "wire" the journey touches.

**Determinism is the load-bearing wall between the two passes.**  A fixture
is keyed by the request's content hash, so the replay answers only if the
replayed request is byte-for-byte the captured one.  Every input that reaches
a prompt is therefore pinned: fixed UUIDs for the campaign and the root,
a fixed theme, a fixed prior proposal, one module-level ``AuthoringConfig``
serving both passes, and wall-clock instants that never enter a prompt (the
stores' ``recorded_at`` columns order the history identically in both passes
because the inserts happen in the same order).  The refusal journey runs on
its own campaign and root, so its prompts cannot collide with the happy
path's.

**The driver wrapper is the addition's own blessing, not a shortcut.**  The
campaign driver that calls the author and the reviser in a loop is a later
spec, and that spec's integration note says a caller wires them *as this
journey does*: a small callable that expands through the author and keeps the
``AuthoredSignal`` (whose ``record`` the tree's ``RefinedSignal`` hand-off
does not carry) — exactly the seam ``NodeExpansion``'s agent parameter and
``_validated_construction``'s duck-typed read are shaped for.

**The module copies are the direct ones.**  No ``create_app()`` here: the
author, the expansion, the stores and the session are imported and composed
as any caller outside the loader composes them, so there is one copy of each
member in the process and the frozen records compare by value.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import discovery
import providers
import pytest
import signal_agent
from dreaming.llm_reviser import LLMReviser
from dreaming.reviser import revise_policy
from signal_agent._llm_author import (
    AUTHORING_REFUSED_CODE,
    AuthoringRefusedError,
    LLMSignalAuthor,
)

# ── The pins, the config, and the campaign's fixed identity ───────────────────


#: The frontier tier §14.1 rotates roots across — two families, distinct
#: providers, as feature 2's own law demands.  Whichever member the rotation
#: picks for a given child is read off the record the author hands back, so
#: the journey never re-predicts the rotation it is verifying.
ROOT_PIN_ANTHROPIC = providers.ModelPin("anthropic", "claude-opus-5", "20260401")
ROOT_PIN_OPENAI = providers.ModelPin("openai", "gpt-5", "20260101")

#: The one cheap depth model below the tier, and the policy pin the offline
#: reviser draws.  Versions are date-shaped and the self-hosted alias — the
#: spellings feature 2's pin parse admits.
DEPTH_PIN = providers.ModelPin("deepseek", "deepseek-chat", "20260101")
POLICY_PIN = providers.ModelPin("self-hosted", "llama-3", "local")

#: One config serving both passes — the same object, so the temperature and
#: the length cap that shape every request (and therefore every fixture's
#: content hash) cannot differ between capture and replay.  The budget
#: ceilings are generous on purpose: a ``BudgetedProvider`` refuses a call
#: once *spent >= ceiling*, and zero (the config default) would refuse the
#: first call of all.
CONFIG = providers.AuthoringConfig(
    root_tier=(ROOT_PIN_ANTHROPIC, ROOT_PIN_OPENAI),
    depth=DEPTH_PIN,
    policy=POLICY_PIN,
    temperature=0.2,
    max_tokens=1024,
    max_input_tokens=200_000,
    max_output_tokens=200_000,
)

#: The campaign and root the happy journey runs on — fixed UUID text, because
#: the child id is ``uuid5(EXPANSION_NAMESPACE, parent)`` and a drifting
#: parent id would silently record fixtures no replay could ask for again.
CAMPAIGN_ID = "4d1f0c52-9a3b-4e7d-8c61-2f8b0d5a7e19"
ROOT_ID = "b2a9e613-7c4d-4f58-9a02-6e3d1c8f4b77"
THEME_ROOT = "short-horizon reversal"

#: The refusal journey's own campaign and root — a distinct pair, so its two
#: prompts hash to their own fixtures rather than colliding with the happy
#: path's (a same-hash different-answer pair is a fixture conflict, and the
#: refusal answers are deliberately not the happy path's answers).
REFUSAL_CAMPAIGN_ID = "7e0b93aa-5c16-4d82-b4f0-91d2a6c3e845"
REFUSAL_ROOT_ID = "c58d1f27-8e93-46b0-a2d4-5f6e7c9b1a03"

#: The deployment's three hashes an attempt's provenance carries beside the
#: authoring terms — 64-hex, as feature 240's value guard demands.
EVALUATOR_HASH = "17" * 32
SNAPSHOT_HASH = "2c" * 32
COST_MODEL_HASH = "41" * 32


# ── The fixture answers: the script a pinned model is fed ────────────────────


#: The root child's authored signal — the body feature 6 must extract, the
#: contract must adopt (a callable ``signal(ctx, seed)``, seed required) and
#: the anti-convergence gate must admit against the prior below.  Kept as a
#: constant of its own so the journey can assert the ``RefinedSignal``'s
#: ``code`` against the exact body, not against a re-parse of the answer.
ROOT_CODE = """\
def signal(ctx, seed):
    tail = ctx.returns.tail(3)
    drawn = [value for value in tail if value < 0.0]
    if not drawn:
        return None
    return -1.0 * drawn[-1]
"""

#: The answer as the model said it — prose, exactly one ```python block, and
#: one ``Mechanism:`` line outside the block.  This whole text is the
#: *proposal* the history persists, asserted verbatim on the proposal row.
ROOT_ANSWER = (
    "Short-term reversal off a forced-liquidation flush.\n"
    "\n"
    "```python\n" + ROOT_CODE + "```\n"
    "\n"
    "Mechanism: Forced liquidation cascades overshoot the printed price "
    "below fair value; the last negative close of a three-bar window "
    "marks the flush, and the snap-back it precedes is the edge.\n"
)

#: The depth child's signal — structurally unlike both the prior and the
#: root's (a for-loop accumulation), so the anti-convergence skeleton check
#: admits it against a history that by then holds both.
DEPTH_CODE = """\
def signal(ctx, seed):
    weighted = 0.0
    for bar in ctx.returns:
        weighted = weighted + bar * seed
    return weighted
"""

DEPTH_ANSWER = (
    "Volatility-scaled drift over the window.\n"
    "\n"
    "```python\n" + DEPTH_CODE + "```\n"
    "\n"
    "Mechanism: Returns drift with realised volatility at short horizons; "
    "a seed-weighted accumulation of the window's bars carries the drift "
    "while the seed sets its scale.\n"
)

#: The campaign's prior proposal, seeded on the root before any call — plain
#: parseable Python (an unparseable held entry is skipped by the gate, and
#: the journey wants the comparison set to be non-empty), and structurally
#: unlike every authored code above.
PRIOR_PROPOSAL = """\
def signal(ctx, seed):
    spread = ctx.returns.max() - ctx.returns.min()
    return spread * seed
"""

#: The incumbent exploration policy the reviser revises, and its two
#: revisions — complete modules, each a distinct text from the incumbent and
#: from each other (feature 271 dedups on the code hash).
INCUMBENT_SOURCE = (
    '"""Frontier exploration policy: breadth first."""\n\n'
    "DEPTH_BREADTH = 4\n"
    "FRONTIER_GAP = 0.25\n"
)
REVISION_ONE_CODE = (
    '"""Frontier exploration policy: breadth first, widened."""\n\n'
    "DEPTH_BREADTH = 6\n"
    "FRONTIER_GAP = 0.25\n"
    "EXPLORE_EPSILON = 0.1\n"
)
REVISION_ONE_ANSWER = "```python\n" + REVISION_ONE_CODE + "```\n"
REVISION_TWO_CODE = (
    '"""Frontier exploration policy: breadth first, annealed."""\n\n'
    "DEPTH_BREADTH = 4\n"
    "FRONTIER_GAP = 0.4\n"
    "ANNEAL_STEPS = 64\n"
)
REVISION_TWO_ANSWER = "```python\n" + REVISION_TWO_CODE + "```\n"

#: The refusal answers — prose with no fenced python block at all, twice, so
#: the parse refuses the first answer, the retry shows the defect back, and
#: the second answer refuses the same way: the whole authoring is refused.
REFUSAL_FIRST_ANSWER = (
    "No signal can be authored: the window's liquidity profile is not "
    "attached to the workspace."
)
REFUSAL_SECOND_ANSWER = (
    "Still no signal: the mechanism needs the venue's fee schedule, which "
    "the workspace does not carry."
)

#: The token accounting each scripted completion reports.  The depth call's
#: cache-read figure (450 of 600 input tokens) is the whole point of the
#: measured-rate assertion; the reviser's two calls share one budget.
ROOT_USAGE = {"input_tokens": 900, "output_tokens": 120, "cache_read_tokens": 0}
DEPTH_USAGE = {"input_tokens": 600, "output_tokens": 140, "cache_read_tokens": 450}
REVISION_ONE_USAGE = {"input_tokens": 400, "output_tokens": 100, "cache_read_tokens": 10}
REVISION_TWO_USAGE = {"input_tokens": 420, "output_tokens": 110, "cache_read_tokens": 0}
REFUSAL_FIRST_USAGE = {"input_tokens": 500, "output_tokens": 80, "cache_read_tokens": 0}
REFUSAL_SECOND_USAGE = {"input_tokens": 510, "output_tokens": 85, "cache_read_tokens": 0}


# ── The scripted model, and the database the tree lives in ────────────────────


class _ScriptedProvider(providers.Provider):
    """A model that answers the script in order — the capture side's wire.

    A real ``Provider`` subclass (so the base class validates the request
    and the completion exactly as it would a live backend's), whose every
    completion names the *request's* model as having served it: the pin's
    own model, which is what ``require_served`` demands, whichever member
    of the frontier tier the rotation routed the call to.  No transport, no
    credential and no socket exist anywhere in it.
    """

    def __init__(self, script: list[tuple[str, dict[str, int]]]) -> None:
        self._script = list(script)
        self.requests: list[providers.Request] = []

    def _complete(self, request: providers.Request) -> providers.Completion:
        self.requests.append(request)
        content, usage = self._script.pop(0)
        return providers.Completion(
            content=content,
            model=request.model,
            usage=providers.Usage(**usage),
        )


def _sqlite_url(path: Path) -> str:
    """The throwaway-database URL spelling every store in this path accepts."""
    return f"sqlite:///{path}"


def _seed_the_tree(database_url: str, *, campaign_id: str, root_id: str) -> None:
    """Create the campaign and its one root node row (depth 0).

    The hand-made ``node`` table carries the columns the writers on this
    path project — the attempt's fifteen, including the agent-provenance
    three feature 203's pin store *refuses* to create for itself — with
    only the identity columns NOT NULL, because a seeded root carries no
    attempt facts yet.  The proposal, rotation, serving-provider and
    cache-rate tables are created lazily by their own stores.
    """
    connection = sqlite3.connect(database_url.removeprefix("sqlite:///"))
    try:
        connection.execute("CREATE TABLE campaign (id TEXT PRIMARY KEY)")
        connection.execute(
            """
            CREATE TABLE node (
                id               TEXT PRIMARY KEY,
                parent_id        TEXT,
                campaign_id      TEXT NOT NULL,
                theme_root       TEXT NOT NULL,
                depth            INTEGER NOT NULL,
                code_hash        TEXT,
                stated_mechanism TEXT,
                artifact_uri     TEXT,
                evaluator_hash   TEXT,
                snapshot_hash    TEXT,
                cost_model_hash  TEXT,
                agent_model_id   TEXT,
                agent_ckpt_hash  TEXT,
                agent_sampling   TEXT,
                fail_class       TEXT
            )
            """
        )
        connection.execute("INSERT INTO campaign (id) VALUES (?)", (campaign_id,))
        connection.execute(
            "INSERT INTO node (id, parent_id, campaign_id, theme_root, depth)"
            " VALUES (?, ?, ?, ?, 0)",
            (root_id, None, campaign_id, THEME_ROOT),
        )
        connection.commit()
    finally:
        connection.close()


class _ArtifactDirectory:
    """The four-method ``ArtifactDirectory`` seam over a plain directory.

    What an ``ArtifactStore`` already satisfies, spelled small so the
    attempt log's staging has somewhere to land without importing the
    artifacts member: ``node_directory`` resolves (creating) the node's
    directory, ``write`` stages one file, ``commit`` is wholesale here, and
    ``discard`` has nothing to undo over a plain filesystem.
    """

    def __init__(self, root: Path) -> None:
        self._root = root

    def node_directory(self, campaign_id: str, node_id: str) -> Path:
        directory = self._root / campaign_id / node_id
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def write(
        self, campaign_id: str, node_id: str, filename: str, body: Any
    ) -> Path:
        target = self.node_directory(campaign_id, node_id) / filename
        if isinstance(body, bytes):
            target.write_bytes(body)
        else:
            target.write_text(str(body), encoding="utf-8")
        return target

    def commit(self, campaign_id: str, node_id: str) -> Path:
        return self.node_directory(campaign_id, node_id)

    def discard(self, campaign_id: str, node_id: str) -> None:
        return None


# ── The choreography — identical over capture's wire and replay's fixtures ────


def _persist_the_attempt(
    log: discovery.AttemptLog, refined: Any, record: Any
) -> None:
    """Record one attempt: the deployment's three hashes beside the record's.

    The authoring third arrives as ``record.attempt_provenance_terms()``
    exactly as feature 4 states the splat, so the node row's agent columns
    and the record cannot disagree about who authored the child.
    """
    provenance = discovery.AttemptProvenance(
        evaluator_hash=EVALUATOR_HASH,
        snapshot_hash=SNAPSHOT_HASH,
        cost_model_hash=COST_MODEL_HASH,
        **record.attempt_provenance_terms(),
    )
    log.record(discovery.Attempt.from_signal(refined, provenance))


def _build_the_author(session: Any, history: Any) -> LLMSignalAuthor:
    """The author over a session whose resolver is the journey's only wire."""
    return LLMSignalAuthor(
        session,
        history_store=history,
        contract=signal_agent.signal_contract(),
        anti_convergence=signal_agent.anti_convergence_gate(),
        guidance=signal_agent.prompt_guidance_gate(),
        config=CONFIG,
    )


def _run_the_campaign(database_url: str, resolve: Any, artifacts: Path) -> dict[str, Any]:
    """One authored refinement, root to depth to revision, over ``database_url``.

    The whole choreography the feature's sentence names, in its order: seed,
    prior proposal, author over session, expand, persist attempt, file the
    authoring record, persist the proposal — twice (depth 1 on the root pin
    the rotation picks, depth 2 on the depth pin) — then the measured cache
    rate and the policy revisions.  The wrapper around the author is the
    caller the later driver spec will own; it keeps the ``AuthoredSignal``
    whose record the tree's hand-off does not carry.
    """
    _seed_the_tree(database_url, campaign_id=CAMPAIGN_ID, root_id=ROOT_ID)
    history = signal_agent.ProposalHistoryStore(
        signal_agent.ProposalStore(database_url)
    )
    history.persist(ROOT_ID, PRIOR_PROPOSAL)

    session = providers.AuthoringSession(CONFIG, resolve)
    author = _build_the_author(session, history)
    authored: dict[str, Any] = {}

    def campaign_driver(workspace: Any) -> Any:
        result = author(workspace)
        authored[str(workspace.node_id)] = result
        return result

    expansion = discovery.NodeExpansion(campaign_driver, database_url)
    log = discovery.AttemptLog(database_url, _ArtifactDirectory(artifacts))

    refined_root = expansion(ROOT_ID)
    root_signal = authored[ROOT_ID]
    _persist_the_attempt(log, refined_root, root_signal.record)
    root_filed = providers.record_authoring(
        root_signal.record, database_url=database_url
    )
    history.persist(refined_root.node_id, root_signal.proposal)

    refined_depth = expansion(refined_root.node_id)
    depth_signal = authored[refined_root.node_id]
    _persist_the_attempt(log, refined_depth, depth_signal.record)
    depth_filed = providers.record_authoring(
        depth_signal.record, database_url=database_url
    )
    history.persist(refined_depth.node_id, depth_signal.proposal)

    rate = providers.record_campaign_cache_rate(
        CAMPAIGN_ID,
        [root_signal.record, depth_signal.record],
        database_url=database_url,
    )

    reviser = LLMReviser(session, config=CONFIG)
    candidates = revise_policy(INCUMBENT_SOURCE, 2, seed=7, reviser=reviser)

    return {
        "refined_root": refined_root,
        "refined_depth": refined_depth,
        "root_signal": root_signal,
        "depth_signal": depth_signal,
        "root_filed": root_filed,
        "depth_filed": depth_filed,
        "rate": rate,
        "candidates": candidates,
        "reviser_records": tuple(reviser.records),
    }


def _run_the_refusal(database_url: str, resolve: Any) -> None:
    """Expand a root whose model answers with no python block, twice.

    The refusal journey: same author, same gates, its own campaign and root
    (seeded with no prior proposal), and an answer that never parses.  The
    expansion raises whatever the author raised — which is the journey's
    own assertion.
    """
    _seed_the_tree(
        database_url,
        campaign_id=REFUSAL_CAMPAIGN_ID,
        root_id=REFUSAL_ROOT_ID,
    )
    author = _build_the_author(
        providers.AuthoringSession(CONFIG, resolve),
        signal_agent.ProposalHistoryStore(
            signal_agent.ProposalStore(database_url)
        ),
    )
    expansion = discovery.NodeExpansion(author, database_url)
    expansion(REFUSAL_ROOT_ID)


# ── Small sqlite readers, for asserting on the rows the journey left ─────────


def _fetch_one(database: Path, statement: str, *parameters: object) -> sqlite3.Row:
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute(statement, parameters).fetchone()
    finally:
        connection.close()
    assert row is not None, f"no row for {statement} {parameters}"
    return row


def _fetch_scalar(database: Path, statement: str, *parameters: object) -> object:
    connection = sqlite3.connect(database)
    try:
        row = connection.execute(statement, parameters).fetchone()
    finally:
        connection.close()
    assert row is not None, f"no row for {statement} {parameters}"
    return row[0]


# ── The journey ───────────────────────────────────────────────────────────────


def test_one_llm_authored_refinement_lands_in_every_store_with_no_network(
    tmp_path: Path,
) -> None:
    """Capture the journey once, then replay it entirely off the fixtures.

    The capture pass runs the choreography over the scripted provider and
    files the exchanges; the replay pass runs the *same* choreography over
    a fresh, identically seeded database whose resolver answers only
    ``RecordedProvider`` — no transport exists to fall back on — and every
    assertion reads the replay's rows.  A fixture answers only a
    byte-identical request, so the replay passing at all is itself the
    assertion that the authored path is deterministic end to end.
    """
    script = [
        (ROOT_ANSWER, ROOT_USAGE),
        (DEPTH_ANSWER, DEPTH_USAGE),
        (REVISION_ONE_ANSWER, REVISION_ONE_USAGE),
        (REVISION_TWO_ANSWER, REVISION_TWO_USAGE),
    ]
    scripted = _ScriptedProvider(script)
    recorder = providers.RecordingProvider(scripted)

    def recorded(pin: providers.ModelPin) -> providers.Provider:
        return recorder

    _run_the_campaign(
        _sqlite_url(tmp_path / "capture.db"), recorded, tmp_path / "capture-artifacts"
    )
    assert len(scripted.requests) == 4

    store = providers.FixtureStore(tmp_path / "fixtures")
    files = store.record_all(recorder.exchanges())
    assert len(files) == 4

    responses = store.responses()

    def replayed(pin: providers.ModelPin) -> providers.Provider:
        return providers.RecordedProvider(responses)

    journey = _run_the_campaign(
        _sqlite_url(tmp_path / "replay.db"), replayed, tmp_path / "replay-artifacts"
    )
    database = tmp_path / "replay.db"

    refined_root = journey["refined_root"]
    refined_depth = journey["refined_depth"]
    root_signal = journey["root_signal"]
    depth_signal = journey["depth_signal"]
    root_record = root_signal.record
    depth_record = depth_signal.record

    # The hand-off carries the authored code and the stated mechanism, and
    # the tree placed the children one level below their parents.  The code
    # is the fenced body — the fence's own line break carries the body's
    # final newline, so the extracted text is the constant without it.
    assert refined_root.code == ROOT_CODE.rstrip("\n")
    assert "overshoot" in (refined_root.stated_mechanism or "")
    assert refined_root.parent_id == ROOT_ID
    assert refined_root.depth == 1
    assert refined_depth.code == DEPTH_CODE.rstrip("\n")
    assert refined_depth.parent_id == refined_root.node_id
    assert refined_depth.depth == 2

    # The record's routing: the root child was served by a tier member under
    # the rotation, the depth child by the one depth pin, and the served
    # model is the pinned one each time.
    assert root_record.role == "root"
    assert root_record.pin in (ROOT_PIN_ANTHROPIC, ROOT_PIN_OPENAI)
    assert root_record.served_model == root_record.pin.model
    assert root_record.tier is not None
    assert depth_record.role == "depth"
    assert depth_record.pin == DEPTH_PIN
    assert depth_record.served_model == DEPTH_PIN.model
    assert depth_record.tier is None

    # The node row carries the pinned agent_model_id and agent_sampling —
    # the triple rendered provider/model/version, and the four sampling
    # settings the record rolled, landed by the attempt's provenance and
    # the authoring recorder alike.
    root_row = _fetch_one(
        database,
        "SELECT agent_model_id, agent_sampling FROM node WHERE id = ?",
        refined_root.node_id,
    )
    assert root_row["agent_model_id"] == root_record.pin.agent_model_id
    assert root_row["agent_model_id"] in {
        ROOT_PIN_ANTHROPIC.agent_model_id,
        ROOT_PIN_OPENAI.agent_model_id,
    }
    assert json.loads(root_row["agent_sampling"]) == root_record.sampling.to_dict()
    assert json.loads(root_row["agent_sampling"])["temperature"] == CONFIG.temperature

    depth_row = _fetch_one(
        database,
        "SELECT agent_model_id FROM node WHERE id = ?",
        refined_depth.node_id,
    )
    assert depth_row["agent_model_id"] == DEPTH_PIN.agent_model_id

    # The root's serving-provider row names the pin's provider — feature
    # 196's row, filed by the recorder against the rotation's own choice —
    # and the depth child wrote no root row at all.
    serving = _fetch_one(
        database,
        "SELECT provider, model, depth FROM root_serving_provider"
        " WHERE node_id = ?",
        refined_root.node_id,
    )
    assert serving["provider"] == root_record.pin.provider
    assert serving["model"] == root_record.pin.model
    assert serving["depth"] == 1
    assert _fetch_scalar(
        database, "SELECT COUNT(*) FROM root_serving_provider"
    ) == 1
    assert journey["root_filed"][2] is not None
    assert journey["depth_filed"][2] is None

    # The proposal row holds the raw answer, verbatim — the whole text the
    # model said, which is what the history replays against.
    assert (
        _fetch_scalar(
            database,
            "SELECT proposal FROM node_proposal WHERE node_id = ?",
            refined_root.node_id,
        )
        == ROOT_ANSWER
    )
    assert (
        _fetch_scalar(
            database,
            "SELECT proposal FROM node_proposal WHERE node_id = ?",
            refined_depth.node_id,
        )
        == DEPTH_ANSWER
    )
    assert _fetch_scalar(database, "SELECT COUNT(*) FROM node") == 3

    # The campaign's measured cache rate, from the depth role's calls alone.
    rate = journey["rate"]
    assert rate.campaign_id == CAMPAIGN_ID
    assert rate.input_tokens == DEPTH_USAGE["input_tokens"]
    assert rate.cache_read_tokens == DEPTH_USAGE["cache_read_tokens"]
    rate_row = _fetch_one(
        database,
        "SELECT input_tokens, cache_read_tokens FROM depth_cache_rate"
        " WHERE campaign_id = ?",
        CAMPAIGN_ID,
    )
    assert rate_row["input_tokens"] == DEPTH_USAGE["input_tokens"]
    assert rate_row["cache_read_tokens"] == DEPTH_USAGE["cache_read_tokens"]

    # The reviser answered through the session's policy pin, and the two
    # revisions are the fixture blocks — complete modules, neither the
    # incumbent nor each other.
    candidates = journey["candidates"]
    assert len(candidates) == 2
    assert {candidate.source for candidate in candidates} == {
        REVISION_ONE_CODE.rstrip("\n"),
        REVISION_TWO_CODE.rstrip("\n"),
    }
    for candidate in candidates:
        assert candidate.source != INCUMBENT_SOURCE
    reviser_records = journey["reviser_records"]
    assert [record.role for record in reviser_records] == ["policy", "policy"]
    assert all(record.pin == POLICY_PIN for record in reviser_records)
    assert all(record.tier is None for record in reviser_records)


def test_an_answer_with_no_python_block_is_retried_once_then_refuses(
    tmp_path: Path,
) -> None:
    """A refusal is captured as fixtures too, and replays as the refusal.

    Two prose answers with no fenced block: the parse refuses the first,
    the author shows the defect back (one retry — ``max_retries``'s
    default), the second refuses the same way, and the whole authoring
    leaves as ``AuthoringRefusedError``.  The two provider calls themselves
    *succeed* — the refusal is the author's judgement, not the provider's —
    so the recorder files both exchanges and the replay reproduces the
    refusal from the recording alone, with no scripted wire left anywhere.
    """
    scripted = _ScriptedProvider(
        [
            (REFUSAL_FIRST_ANSWER, REFUSAL_FIRST_USAGE),
            (REFUSAL_SECOND_ANSWER, REFUSAL_SECOND_USAGE),
        ]
    )
    recorder = providers.RecordingProvider(scripted)

    def recorded(pin: providers.ModelPin) -> providers.Provider:
        return recorder

    with pytest.raises(AuthoringRefusedError):
        _run_the_refusal(_sqlite_url(tmp_path / "capture.db"), recorded)
    # The first attempt and its one retry — the whole cost of the refusal.
    assert len(scripted.requests) == 2

    store = providers.FixtureStore(tmp_path / "fixtures")
    files = store.record_all(recorder.exchanges())
    # The retry's prompt carries the refused answer and the defect turn, so
    # it hashes to its own fixture: two files, not one.
    assert len(files) == 2

    responses = store.responses()

    def replayed(pin: providers.ModelPin) -> providers.Provider:
        return providers.RecordedProvider(responses)

    database = tmp_path / "replay.db"
    with pytest.raises(AuthoringRefusedError) as caught:
        _run_the_refusal(_sqlite_url(database), replayed)

    message = str(caught.value)
    assert message.startswith(f"{AUTHORING_REFUSED_CODE}:")
    assert "authored_output" in message

    # The refused authoring wrote no child row: the tree still holds only
    # the seeded root, and no proposal was recorded for the campaign.
    assert _fetch_scalar(database, "SELECT COUNT(*) FROM node") == 1
    assert _fetch_scalar(database, "SELECT COUNT(*) FROM node_proposal") == 0
