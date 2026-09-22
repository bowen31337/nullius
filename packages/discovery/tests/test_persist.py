"""Feature 240: every attempt into the tree, with its artifact.

app_spec.xml, "Discovery Orchestrator & Campaigns", feature 240 —
*"System persists every attempt into the node table together with its
full artifact, including failures"* — and the suite is organised around
the four claims that sentence makes:

* **the row** — an attempt lands in the ``node`` table with the columns
  §9.1 declares, and the seven metrics and ``created_at`` are *not*
  written (they belong to step 12 and to a migration that does not
  exist);
* **the artifact** — the attempt's source and its execution trace reach
  §9.2's directory *and* the row's ``artifact_uri`` names that very
  directory;
* **including failures** — a failed attempt is written by the same call,
  into the same table, with the same directory, carrying its
  ``fail_class`` and the evidence of what failed;
* **§14's idempotence, on the tree's side** — a second attempt of one job
  refreshes the row its derived identity already names rather than
  adding a second, and re-publishes the directory wholesale.

The store is a hand-written double rather than the artifacts member's
:class:`~artifacts.ArtifactStore` — this member may not import that one,
and the seam is a Protocol precisely so a double is a legal
implementation rather than a mock.  It is written out in full below
because the *layout* is the thing under test: the double builds
``<root>/<campaign_id>/<node_id>`` exactly as the layout contract says,
so a test can assert on the bytes without a second copy of the rule.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import sys
import uuid
from contextlib import closing
from pathlib import Path
from urllib.parse import urlparse

import pytest
from discovery import (
    ARTIFACT_URI_COLUMN,
    FAIL_CLASS_COLUMN,
    FAIL_CLASSES,
    MEASURED_FILENAMES,
    SOURCE_FILENAME,
    TRACE_FILENAME,
    Attempt,
    AttemptLog,
    AttemptLogError,
    AttemptProvenance,
    WorkerInterrupted,
    attempt_node_id,
    classify_failure,
    record_attempts,
    refined_node_id,
)
from discovery.expansion import RefinedSignal

REPO_ROOT = Path(__file__).resolve().parents[3]

#: §9.2's five measured names, restated as data rather than read off the
#: member — the *layout* is the contract under test, so a test that
#: imported the member's own tuple would pass for a misspelling both
#: sides shared.  The member's :data:`discovery.MEASURED_FILENAMES` is
#: pinned equal to this below.
MEASURED_FILES = (
    "signal_returns.parquet",
    "ic_series.parquet",
    "turnover_series.parquet",
    "decay_profile.json",
    "regime_attribution.json",
)

#: A digest-shaped authoring record the tests reuse; every field of the
#: provenance triple must be a real 64-hex sha256, so a literal 'abc' would
#: be exercising the refusal rather than the write.
DIGEST_A = hashlib.sha256(b"evaluator").hexdigest()
DIGEST_B = hashlib.sha256(b"snapshot").hexdigest()
DIGEST_C = hashlib.sha256(b"cost-model").hexdigest()
DIGEST_D = hashlib.sha256(b"weights").hexdigest()

SOURCE = "def signal(ctx):\n    return ctx.close.pct_change(20)\n"


# -- The artifact seam, hand-written -------------------------------------------------


class MemoryDirectory:
    """An ``ArtifactDirectory`` that keeps §9.2's layout in memory.

    Written out rather than mocked, because the one thing this feature
    must get right about the artifact half is *where the bytes go*: the
    double resolves ``<root>/<campaign_id>/<node_id>`` the way the layout
    contract spells it, so a test asserting on
    :attr:`AttemptRecord.artifact_uri` is asserting on the same path the
    write landed in rather than on a stub's convenience return.

    It reproduces the store's two-phase discipline faithfully, because
    the discipline is load-bearing: :meth:`write` stages, :meth:`commit`
    publishes the whole staged set at once, and :meth:`discard` throws the
    staged set away.  A read therefore cannot see a half-written attempt,
    which is what lets the refusal test assert that a refused attempt
    published *nothing*.

    **The commit replaces wholesale**, which is the store's own documented
    semantics — *"a file the retry did not stage is gone, which is what
    'refresh' means for a directory that is one unit"* — and it is the
    reason feature 240 has to carry the measured five forward at all.  A
    double that merged instead would hide that whole class of bug, so the
    fake is written to the contract rather than to convenience, and
    :class:`TestTheCarryForwardAgainstTheRealStore` runs the same scenario
    through the artifacts member's own store so the two cannot drift.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self._staged: dict[tuple[str, str], dict[str, bytes]] = {}
        self._published: dict[tuple[str, str], dict[str, bytes]] = {}
        self.commits: list[tuple[str, str]] = []
        self.discards: list[tuple[str, str]] = []

    def node_directory(self, campaign_id: str, node_id: str) -> Path:
        return self.root / str(campaign_id) / str(node_id)

    def write(
        self,
        campaign_id: str,
        node_id: str,
        filename: str,
        data: bytes | bytearray | memoryview | str,
    ) -> Path:
        staged = self._staged.setdefault((str(campaign_id), str(node_id)), {})
        staged[filename] = data.encode("utf-8") if isinstance(data, str) else bytes(data)
        return self.node_directory(campaign_id, node_id) / filename

    def commit(self, campaign_id: str, node_id: str) -> Path:
        """Publish the staged set as the directory, replacing it wholesale.

        The replace is the contract (see the class docstring): the
        directory holds *exactly* what was staged, never a splice with a
        prior version.  An empty staged set is a no-op rather than a
        deletion, matching the real store's refusal to commit nothing.
        """
        key = (str(campaign_id), str(node_id))
        staged = self._staged.pop(key, {})
        if not staged:
            raise AssertionError(
                "nothing is staged — the real store refuses an empty commit, "
                "and a double that published one would hide the case"
            )
        self._published[key] = dict(staged)
        directory = self.node_directory(campaign_id, node_id)
        if directory.exists():
            shutil.rmtree(directory)
        directory.mkdir(parents=True, exist_ok=True)
        for name, body in staged.items():
            (directory / name).write_bytes(body)
        self.commits.append(key)
        return directory

    def discard(self, campaign_id: str, node_id: str) -> None:
        key = (str(campaign_id), str(node_id))
        self._staged.pop(key, None)
        self.discards.append(key)

    def read(self, campaign_id: str, node_id: str, filename: str) -> bytes:
        """One *published* file's bytes — the seam's optional read.

        Modeled on the real store's: a name that is not in the published
        directory raises, which is the shape :func:`_published_bytes`
        absorbs.  A double that answered ``None`` instead would test the
        wrong branch.

        This path is reached only when the double is made to disagree with
        itself — :meth:`AttemptLog._restage_published` asks :meth:`files`
        first and reads only the names it listed, so a consistent store
        never raises here.  The two tests that drive it are the ones that
        break that consistency deliberately, because the guard's whole
        subject is what a store does when it is *inconsistent*.
        """
        key = (str(campaign_id), str(node_id))
        try:
            return self._published[key][filename]
        except KeyError as exc:
            raise FileNotFoundError(
                f"{filename} is not published for node {node_id}"
            ) from exc

    # -- Test-side readers, not part of the seam -----------------------------

    def files(self, campaign_id: str, node_id: str) -> dict[str, bytes]:
        """What a reader would find in the node's published directory."""
        return dict(self._published.get((str(campaign_id), str(node_id)), {}))

    def staged(self, campaign_id: str, node_id: str) -> dict[str, bytes]:
        """What is currently staged and unpublished for the node."""
        return dict(self._staged.get((str(campaign_id), str(node_id)), {}))


class RefusingDirectory(MemoryDirectory):
    """A directory whose ``write`` of one named file raises.

    For the half-state test: the row is written and the artifact is not,
    and the refusal must name exactly that rather than surfacing whatever
    the store raised as though the attempt were simply unsaved.
    """

    def __init__(self, root: Path, refuse: str) -> None:
        super().__init__(root)
        self.refuse = refuse

    def write(self, campaign_id, node_id, filename, data):  # type: ignore[override]
        if filename == self.refuse:
            raise OSError(f"{filename} could not be staged")
        return super().write(campaign_id, node_id, filename, data)


class SeamlessDirectory:
    """An object that does not speak the four-method seam at all."""


# -- Fixtures ----------------------------------------------------------------------


@pytest.fixture
def directory(tmp_path: Path) -> MemoryDirectory:
    """A fresh in-memory artifact store under the test's own tmp_path."""
    return MemoryDirectory(tmp_path / "artifacts")


@pytest.fixture
def provenance() -> AttemptProvenance:
    """The deployment's record of the world an attempt ran in."""
    return AttemptProvenance(
        evaluator_hash=DIGEST_A,
        snapshot_hash=DIGEST_B,
        cost_model_hash=DIGEST_C,
        agent_model_id="anthropic/claude-opus-5/2026-01",
        agent_sampling={"temperature": 0.7, "top_p": 0.95, "thinking": True, "seed": 41},
        agent_ckpt_hash=DIGEST_D,
    )


@pytest.fixture
def tree(migrated_with_attempt_columns: str, campaign_id: str, plant_root):
    """``(database_url, campaign_id, parent_id)`` over a fully widened tree.

    The parent is planted as a **root** — ``parent_id NULL``, ``depth 0``
    — because every attempt in this suite is a refinement of one, and the
    identity law derives a child from the parent it resumes.  None of the
    attempt's own columns are pre-filled: the whole point of feature 240
    is that nothing is in the tree until an attempt is recorded.
    """
    parent = plant_root(campaign_id, depth=0)
    return migrated_with_attempt_columns, campaign_id, parent


@pytest.fixture
def signal(tree) -> RefinedSignal:
    """Feature 239's hand-off — the one refined signal an expansion answers.

    Built directly rather than by running an expansion, because this
    suite is about the *write*: the hand-off's shape is feature 239's
    contract and its own suite pins it, so constructing it here keeps
    this file's failures about persistence.
    """
    _, campaign, parent = tree
    return RefinedSignal(
        node_id=attempt_node_id(parent),
        parent_id=parent,
        campaign_id=campaign,
        theme_root="macro",
        depth=1,
        code=SOURCE,
        code_hash=hashlib.sha256(SOURCE.encode("utf-8")).hexdigest(),
        stated_mechanism="Fades crowded carry: enter when funding is extreme.",
    )


@pytest.fixture
def attempt(signal, provenance) -> Attempt:
    """The succeeded attempt every test starts from."""
    return Attempt.from_signal(signal, provenance)


@pytest.fixture
def log(tree, directory) -> AttemptLog:
    """The store under test, over the widened tree and the double."""
    database_url, _, _ = tree
    return AttemptLog(database_url, directory)


def _path_of(database_url: str) -> Path:
    """The file behind a ``sqlite:///`` URL, for raw SQL in a test."""
    return Path(urlparse(database_url).path.removeprefix("/"))


def _row(database_url: str, node_id: str) -> dict[str, object]:
    """Read one node row back as a mapping, or fail with the id named."""
    with closing(sqlite3.connect(_path_of(database_url))) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT * FROM node WHERE id = ?", (node_id,)
        ).fetchone()
    assert row is not None, f"no node row for {node_id}"
    return dict(row)


def _columns(database_url: str) -> list[str]:
    """The live ``node`` table's column names."""
    with closing(sqlite3.connect(_path_of(database_url))) as connection:
        return [str(row[1]) for row in connection.execute("PRAGMA table_info(node)")]


def _plant_sibling(plant_root, campaign: str) -> str:
    """Plant one more root under the campaign, for a batch of two attempts."""
    return plant_root(campaign, depth=0)


# -- The vocabulary ------------------------------------------------------------------


def test_the_measured_names_are_section_9_2s_five_in_order():
    """§9.2's layout, as literals — the five step 12 owns.

    The member's tuple is a restatement of the architecture doc's own
    list, so both are pinned: the doc's order and the member's, because
    a tuple that drifted from the layout would carry a file to a name no
    reader opens.
    """
    assert MEASURED_FILENAMES == MEASURED_FILES


def test_fail_classes_are_section_9_1s_four():
    """§9.1's annotation, verbatim, in the order the spec lists it."""
    assert FAIL_CLASSES == ("ok", "timeout", "error", "tripwire_fail")


def test_classify_failure_none_is_ok():
    """The attempt that answered is ``ok`` — a recorded outcome."""
    assert classify_failure(None) == "ok"


def test_classify_failure_a_raised_timeout_is_error_not_timeout():
    """A *raised* timeout is a host fault, not §5.2's kill.

    The one place the obvious reading is wrong, so it is asserted rather
    than left to the docstring.  §5.2's timeout is a control: the sandbox
    hard-kills the child and returns its class as a *value* — "a failed run
    is a value the pipeline records" — which is why
    :func:`evaluator.failure_outcome` maps every raised exception to
    ``error`` and says so in as many words.  Reading ``TimeoutError`` as
    ``timeout`` here would record a host-side fault as the budget being
    enforced, and would give one exception name two outcomes in two
    members sharing one vocabulary.

    ``timeout`` still reaches the column — through the *stated* path, by
    the caller that watched the kill (:func:`test_classify_failure_accepts_a_stated_class`
    and :func:`test_a_timeout_is_persisted_like_any_other_attempt`).
    """
    assert classify_failure(TimeoutError("hard kill")) == "error"


def test_classify_failure_other_exceptions_are_error():
    """``oom``, ``crash``, ``violation`` and an agent's own exception."""
    for failure in (RuntimeError("boom"), MemoryError(), ValueError("payload")):
        assert classify_failure(failure) == "error"


def test_classify_failure_of_an_interruption_is_error():
    """§14's reclaim gets no fifth word — the marker is what distinguishes it.

    ``WorkerInterrupted`` is a scheduled event rather than a fault, and
    the closed four-word vocabulary is §9.1's; what answers *to what?* is
    the trace's ``error_class``, which carries the marker's own name.
    """
    assert classify_failure(WorkerInterrupted("reclaimed")) == "error"


def test_classify_failure_accepts_a_stated_class():
    """A caller that already knows the outcome states it."""
    assert classify_failure("tripwire_fail") == "tripwire_fail"


def test_classify_failure_refuses_a_drifted_word():
    """A word outside §9.1's four is refused rather than passed through."""
    with pytest.raises(AttemptLogError, match="not a failure class"):
        classify_failure("failed")


def test_classify_failure_refuses_an_unrecognised_value():
    """A value that is none of the three shapes must not read as ``ok``."""
    with pytest.raises(AttemptLogError, match="classifies an exception"):
        classify_failure(object())


# -- The identity law ----------------------------------------------------------------


def test_attempt_node_id_is_the_expansion_derivation():
    """Feature 240 does not mint identities: it restates feature 239's."""
    parent = str(uuid.uuid4())
    assert attempt_node_id(parent) == refined_node_id(parent)


def test_attempt_node_id_is_stable_across_calls():
    """Derived, so two attempts of one job name one node."""
    parent = str(uuid.uuid4())
    assert attempt_node_id(parent) == attempt_node_id(parent)


def test_attempts_under_different_parents_are_different_nodes():
    """Distinct parents derive distinct children."""
    assert attempt_node_id(str(uuid.uuid4())) != attempt_node_id(str(uuid.uuid4()))


# -- The provenance value -------------------------------------------------------------


def test_provenance_canonicalizes_hashes_to_lowercase(provenance):
    """Case is folded, because two spellings of one digest is the drift."""
    upper = AttemptProvenance(
        evaluator_hash=DIGEST_A.upper(),
        snapshot_hash=DIGEST_B,
        cost_model_hash=DIGEST_C,
        agent_model_id="anthropic/claude-opus-5/2026-01",
        agent_sampling={"seed": 1},
    )
    assert upper.evaluator_hash == DIGEST_A


def test_provenance_refuses_a_truncated_hash():
    """A hash that is not 64 hex characters names nothing comparable."""
    with pytest.raises(AttemptLogError, match="64 hexadecimal"):
        AttemptProvenance(
            evaluator_hash=DIGEST_A[:32],
            snapshot_hash=DIGEST_B,
            cost_model_hash=DIGEST_C,
            agent_model_id="anthropic/claude-opus-5/2026-01",
        )


def test_provenance_refuses_a_container_image_tag():
    """The ``sha256:``-prefixed form the ledger's validator refuses too."""
    with pytest.raises(AttemptLogError, match="64 hexadecimal"):
        AttemptProvenance(
            evaluator_hash=f"sha256:{DIGEST_A}",
            snapshot_hash=DIGEST_B,
            cost_model_hash=DIGEST_C,
            agent_model_id="anthropic/claude-opus-5/2026-01",
        )


def test_provenance_refuses_a_blank_authoring_model():
    """§9.1 types ``agent_model_id`` NOT NULL, and blank is not a model."""
    with pytest.raises(AttemptLogError, match="non-empty text"):
        AttemptProvenance(
            evaluator_hash=DIGEST_A,
            snapshot_hash=DIGEST_B,
            cost_model_hash=DIGEST_C,
            agent_model_id="   ",
        )


def test_provenance_canonicalizes_sampling_json():
    """Key order is dropped, so two equal samplings stage equal bytes."""
    unordered = AttemptProvenance(
        evaluator_hash=DIGEST_A,
        snapshot_hash=DIGEST_B,
        cost_model_hash=DIGEST_C,
        agent_model_id="anthropic/claude-opus-5/2026-01",
        agent_sampling={"seed": 7, "temperature": 0.2},
    )
    ordered = AttemptProvenance(
        evaluator_hash=DIGEST_A,
        snapshot_hash=DIGEST_B,
        cost_model_hash=DIGEST_C,
        agent_model_id="anthropic/claude-opus-5/2026-01",
        agent_sampling={"temperature": 0.2, "seed": 7},
    )
    assert unordered.agent_sampling == ordered.agent_sampling
    assert unordered.agent_sampling == '{"seed":7,"temperature":0.2}'


def test_provenance_accepts_sampling_as_json_text():
    """Text that parses to an object is canonicalized, not refused."""
    value = AttemptProvenance(
        evaluator_hash=DIGEST_A,
        snapshot_hash=DIGEST_B,
        cost_model_hash=DIGEST_C,
        agent_model_id="anthropic/claude-opus-5/2026-01",
        agent_sampling='{"seed": 3}',
    )
    assert value.agent_sampling == '{"seed":3}'


def test_provenance_refuses_sampling_text_that_does_not_parse():
    """Text no reader can parse is a record of nothing."""
    with pytest.raises(AttemptLogError, match="does not parse"):
        AttemptProvenance(
            evaluator_hash=DIGEST_A,
            snapshot_hash=DIGEST_B,
            cost_model_hash=DIGEST_C,
            agent_model_id="anthropic/claude-opus-5/2026-01",
            agent_sampling="{seed: 3}",
        )


def test_provenance_refuses_a_non_object_sampling():
    """§9.1 spells the column after the four dice it holds."""
    with pytest.raises(AttemptLogError, match="must be a JSON object"):
        AttemptProvenance(
            evaluator_hash=DIGEST_A,
            snapshot_hash=DIGEST_B,
            cost_model_hash=DIGEST_C,
            agent_model_id="anthropic/claude-opus-5/2026-01",
            agent_sampling=[0.7, 0.95],
        )


def test_provenance_permits_a_null_checkpoint():
    """§9.1's ``non-null for self-hosted weights`` — the null is a fact."""
    hosted = AttemptProvenance(
        evaluator_hash=DIGEST_A,
        snapshot_hash=DIGEST_B,
        cost_model_hash=DIGEST_C,
        agent_model_id="anthropic/claude-opus-5/2026-01",
        agent_ckpt_hash=None,
    )
    assert hosted.agent_ckpt_hash is None


# -- The attempt value ----------------------------------------------------------------


def test_from_signal_takes_the_five_derived_facts_off_the_signal(signal, provenance):
    """The hand-off's own columns, unaltered."""
    built = Attempt.from_signal(signal, provenance)
    assert built.parent_id == signal.parent_id
    assert built.campaign_id == signal.campaign_id
    assert built.theme_root == signal.theme_root
    assert built.depth == signal.depth
    assert built.code == signal.code
    assert built.code_hash == signal.code_hash
    assert built.stated_mechanism == signal.stated_mechanism


def test_an_attempt_that_answered_is_ok(attempt):
    """``ok`` is the default and the property agrees with it."""
    assert attempt.fail_class == "ok"
    assert attempt.ok is True
    assert attempt.error_class is None
    assert attempt.error_message is None


def test_from_signal_classifies_a_failure_from_its_exception(signal, provenance):
    """A caller holding the exception gets the class and the evidence.

    A generic exception, so this is the ``error`` path; the timeout class
    takes the stated path and is covered separately, because a *raised*
    ``TimeoutError`` is a host fault rather than §5.2's kill.
    """
    built = Attempt.from_signal(signal, provenance, error=RuntimeError("died"))
    assert built.fail_class == "error"
    assert built.ok is False
    assert built.error_class == "RuntimeError"
    assert built.error_message == "died"


def test_from_signal_takes_a_stated_timeout_with_its_evidence(signal, provenance):
    """§5.2's kill: the class stated by the caller that watched it."""
    built = Attempt.from_signal(
        signal,
        provenance,
        fail_class="timeout",
        error=RuntimeError("hard-killed at the 30s wall"),
    )
    assert built.fail_class == "timeout"
    assert built.error_class == "RuntimeError"


def test_a_stated_class_alone_is_refused_and_that_is_the_rule(signal, provenance):
    """The class without evidence is not a shape this value accepts.

    Falsifiable in one line, so it is pinned rather than left to the
    docstring: ``from_signal(signal, prov, fail_class="timeout")`` is
    *refused*, because :class:`Attempt` requires a failure to name what
    failed.  This is the reading a caller that holds §5.2's kill will
    reach for first — the value carries the class, so surely the class is
    enough — and the point of the refusal is that it is not: *"a failure
    logged with no evidence of what failed is a hole in exactly the record
    'including failures' points at"*.

    The honest route for such a caller is either of the two below.
    """
    with pytest.raises(AttemptLogError, match="no error_class"):
        Attempt.from_signal(signal, provenance, fail_class="timeout")


def test_the_kills_own_detail_is_the_evidence_a_value_caller_passes(
    signal, provenance
):
    """How a caller holding a sandbox *value* records §5.2's timeout.

    §5.2's timeout has no exception to hand over — the sandbox hard-kills
    and returns its class as a value — so a caller that never saw an
    exception must supply the evidence some other way.  Both honest routes
    are asserted here, because the docstring claims they exist and a claim
    about an unavailable path is the kind of thing that stays wrong:

    * the value's own ``detail`` travelling as the ``error``'s message, and
    * a directly constructed :class:`Attempt` naming the evidence as text,
      for a caller whose evidence never was an exception object at all.
    """
    # Route one: the value's detail, carried on an exception the caller
    # raises to name the fact.  ``TimeoutKill.detail`` is feature 163's own
    # text for it.
    built = Attempt.from_signal(
        signal,
        provenance,
        fail_class="timeout",
        error=RuntimeError("wall clock exceeded: 31.0s of 30.0s"),
    )
    assert built.fail_class == "timeout"
    assert "wall clock" in built.error_message

    # Route two: no exception in hand, evidence as text.
    direct = Attempt(
        parent_id=signal.parent_id,
        campaign_id=signal.campaign_id,
        theme_root=signal.theme_root,
        depth=signal.depth,
        code=signal.code,
        code_hash=signal.code_hash,
        stated_mechanism=None,
        provenance=provenance,
        fail_class="timeout",
        error_class="SandboxTimeoutError",
        error_message="hard kill at the 30s wall",
    )
    assert direct.fail_class == "timeout"
    assert direct.error_class == "SandboxTimeoutError"
    assert direct.node_id == built.node_id
    # And the trace answers *to what?* from either route.
    assert direct.trace()["error_class"] == "SandboxTimeoutError"


def test_from_signal_keeps_a_stated_class_beside_the_exception(signal, provenance):
    """The stated class and the held evidence are both kept."""
    built = Attempt.from_signal(
        signal, provenance, fail_class="tripwire_fail", error=RuntimeError("peeked")
    )
    assert built.fail_class == "tripwire_fail"
    assert built.error_class == "RuntimeError"


def test_from_signal_carries_feature_244s_retry_history(signal, provenance):
    """``attempts`` is 244's ``len(interruptions) + 1``, exactly."""
    interruptions = (
        {"slot": 0, "error_class": "WorkerInterrupted", "error_message": "reclaimed"},
        {"slot": 2, "error_class": "WorkerInterrupted", "error_message": "reclaimed"},
    )
    built = Attempt.from_signal(signal, provenance, interruptions=interruptions)
    assert built.attempts == 3
    assert built.attempt == 1
    assert built.interruptions == interruptions


def test_attempt_refuses_a_code_hash_that_is_not_sha256_of_its_code(
    signal, provenance
):
    """§9.1's identity: the node *is* its code."""
    with pytest.raises(AttemptLogError, match="sha256"):
        Attempt(
            parent_id=signal.parent_id,
            campaign_id=signal.campaign_id,
            theme_root=signal.theme_root,
            depth=1,
            code=SOURCE,
            code_hash=hashlib.sha256(b"other source").hexdigest(),
            stated_mechanism=None,
            provenance=provenance,
        )


def test_attempt_refuses_no_source_at_all(signal, provenance):
    """0117's own words: a node with no code hash is not a node at all."""
    with pytest.raises(AttemptLogError, match="no source"):
        Attempt(
            parent_id=signal.parent_id,
            campaign_id=signal.campaign_id,
            theme_root=signal.theme_root,
            depth=1,
            code="   ",
            code_hash=hashlib.sha256(b"   ").hexdigest(),
            stated_mechanism=None,
            provenance=provenance,
        )


def test_attempt_refuses_a_depth_below_one(signal, provenance):
    """A refined attempt is never a root — roots are planted with a theme."""
    with pytest.raises(AttemptLogError, match="never a root"):
        Attempt(
            parent_id=signal.parent_id,
            campaign_id=signal.campaign_id,
            theme_root=signal.theme_root,
            depth=0,
            code=SOURCE,
            code_hash=signal.code_hash,
            stated_mechanism=None,
            provenance=provenance,
        )


def test_attempt_refuses_a_boolean_depth(signal, provenance):
    """``True`` is not a count — the trap every ordinal in this member avoids."""
    with pytest.raises(AttemptLogError, match="depth"):
        Attempt(
            parent_id=signal.parent_id,
            campaign_id=signal.campaign_id,
            theme_root=signal.theme_root,
            depth=True,
            code=SOURCE,
            code_hash=signal.code_hash,
            stated_mechanism=None,
            provenance=provenance,
        )


def test_attempt_refuses_a_drifted_fail_class(signal, provenance):
    """The column's closed vocabulary, enforced inside the value."""
    with pytest.raises(AttemptLogError, match="fail_class"):
        Attempt(
            parent_id=signal.parent_id,
            campaign_id=signal.campaign_id,
            theme_root=signal.theme_root,
            depth=1,
            code=SOURCE,
            code_hash=signal.code_hash,
            stated_mechanism=None,
            provenance=provenance,
            fail_class="failed",
        )


def test_attempt_refuses_a_failure_with_no_evidence(signal, provenance):
    """A failure logged with no evidence is the hole 'including failures' means."""
    with pytest.raises(AttemptLogError, match="no error_class"):
        Attempt(
            parent_id=signal.parent_id,
            campaign_id=signal.campaign_id,
            theme_root=signal.theme_root,
            depth=1,
            code=SOURCE,
            code_hash=signal.code_hash,
            stated_mechanism=None,
            provenance=provenance,
            fail_class="error",
        )


def test_attempt_refuses_an_error_beside_ok(signal, provenance):
    """Two contradictory answers to one question."""
    with pytest.raises(AttemptLogError, match="fail_class 'ok'"):
        Attempt(
            parent_id=signal.parent_id,
            campaign_id=signal.campaign_id,
            theme_root=signal.theme_root,
            depth=1,
            code=SOURCE,
            code_hash=signal.code_hash,
            stated_mechanism=None,
            provenance=provenance,
            error_class="RuntimeError",
        )


def test_attempt_refuses_a_run_ordinal_above_its_own_count(signal, provenance):
    """A fourth run of three describes a history nothing can reconcile."""
    with pytest.raises(AttemptLogError, match="is run 4 of 3"):
        Attempt(
            parent_id=signal.parent_id,
            campaign_id=signal.campaign_id,
            theme_root=signal.theme_root,
            depth=1,
            code=SOURCE,
            code_hash=signal.code_hash,
            stated_mechanism=None,
            provenance=provenance,
            attempt=4,
            attempts=3,
        )


def test_attempt_refuses_an_interruption_count_that_disagrees(
    signal, provenance
):
    """244's law, restated as a refusal rather than trusted."""
    with pytest.raises(AttemptLogError, match="len\\(interruptions\\) \\+ 1"):
        Attempt(
            parent_id=signal.parent_id,
            campaign_id=signal.campaign_id,
            theme_root=signal.theme_root,
            depth=1,
            code=SOURCE,
            code_hash=signal.code_hash,
            stated_mechanism=None,
            provenance=provenance,
            attempts=2,
            interruptions=(),
        )


def test_attempt_refuses_a_blank_stated_mechanism(signal, provenance):
    """The honest absent value is ``None``, not a blank string."""
    with pytest.raises(AttemptLogError, match="stated_mechanism"):
        Attempt(
            parent_id=signal.parent_id,
            campaign_id=signal.campaign_id,
            theme_root=signal.theme_root,
            depth=1,
            code=SOURCE,
            code_hash=signal.code_hash,
            stated_mechanism="  ",
            provenance=provenance,
        )


def test_a_null_stated_mechanism_is_permitted(signal, provenance):
    """0117's honest NULL: dedup and human review only, never scored."""
    built = Attempt(
        parent_id=signal.parent_id,
        campaign_id=signal.campaign_id,
        theme_root=signal.theme_root,
        depth=1,
        code=SOURCE,
        code_hash=signal.code_hash,
        stated_mechanism=None,
        provenance=provenance,
    )
    assert built.stated_mechanism is None


def test_attempt_refuses_a_non_uuid_parent(provenance):
    """The tree's key is a UUID; a value it cannot hold names nothing."""
    with pytest.raises(AttemptLogError, match="not a node id|must be a string"):
        Attempt(
            parent_id="not-a-uuid",
            campaign_id=str(uuid.uuid4()),
            theme_root="macro",
            depth=1,
            code=SOURCE,
            code_hash=hashlib.sha256(SOURCE.encode()).hexdigest(),
            stated_mechanism=None,
            provenance=provenance,
        )


def test_dataclasses_replace_revalidates(signal, provenance):
    """The law lives inside the value — a rebuild cannot slip past it."""
    import dataclasses

    good = Attempt.from_signal(signal, provenance)
    with pytest.raises(AttemptLogError, match="fail_class"):
        dataclasses.replace(good, fail_class="failed")


# -- The row -----------------------------------------------------------------------


def test_row_carries_the_columns_section_9_1_names(attempt):
    """The seven hand-off columns, the provenance trio and the class."""
    row = attempt.row("file:///artifacts/x/y")
    assert row["id"] == attempt.node_id
    assert row["parent_id"] == attempt.parent_id
    assert row["campaign_id"] == attempt.campaign_id
    assert row["theme_root"] == attempt.theme_root
    assert row["depth"] == attempt.depth
    assert row["code_hash"] == attempt.code_hash
    assert row["stated_mechanism"] == attempt.stated_mechanism
    assert row[ARTIFACT_URI_COLUMN] == "file:///artifacts/x/y"
    assert row["evaluator_hash"] == DIGEST_A
    assert row["snapshot_hash"] == DIGEST_B
    assert row["cost_model_hash"] == DIGEST_C
    assert row["agent_model_id"] == "anthropic/claude-opus-5/2026-01"
    assert row["agent_ckpt_hash"] == DIGEST_D
    assert row["fail_class"] == "ok"


def test_row_writes_no_metrics_and_no_created_at(attempt):
    """Step 12's measured numbers and a column no migration declares.

    The seven are §9.1's own spellings — a test naming ``sharpe`` would
    pass against a row that silently carried ``ic_mean``, since neither
    is the other.  ``created_at`` is the eighth: §9.1 declares it NOT
    NULL and no migration creates it, and ``0118``'s docstring argues the
    absence is honest ("the honest form is a feature that names it, not a
    sixth column") — feature 240 names ``fail_class``, not this.
    """
    row = attempt.row("file:///artifacts/x/y")
    for name in (
        "ic_mean",
        "ic_tstat",
        "ir_standalone",
        "ir_marginal",
        "turnover",
        "cost_adjusted_ir",
        "perturb_stability",
        "created_at",
    ):
        assert name not in row


def test_row_refuses_a_blank_artifact_uri(attempt):
    """§9.1 types the column NOT NULL and describes it as required."""
    with pytest.raises(AttemptLogError, match="artifact_uri"):
        attempt.row("")


# -- The write ---------------------------------------------------------------------


def test_record_writes_the_node_row(log, tree, attempt):
    """The row lands with the attempt's own identity and facts."""
    database_url, campaign, parent = tree
    record = log.record(attempt)
    assert record.node_id == attempt.node_id
    assert record.appended is True
    row = _row(database_url, attempt.node_id)
    assert str(row["id"]) == attempt.node_id
    assert str(row["parent_id"]) == parent
    assert str(row["campaign_id"]) == campaign
    assert row["theme_root"] == "macro"
    assert row["depth"] == 1
    assert row["code_hash"] == attempt.code_hash
    assert row["fail_class"] == "ok"


def test_record_writes_the_provenance_trio(log, tree, attempt):
    """§9.1's four hashes and the authoring record reach the row."""
    database_url, _, _ = tree
    log.record(attempt)
    row = _row(database_url, attempt.node_id)
    assert row["evaluator_hash"] == DIGEST_A
    assert row["snapshot_hash"] == DIGEST_B
    assert row["cost_model_hash"] == DIGEST_C
    assert row["agent_ckpt_hash"] == DIGEST_D
    assert row["agent_model_id"] == "anthropic/claude-opus-5/2026-01"
    assert json.loads(row["agent_sampling"]) == {
        "temperature": 0.7,
        "top_p": 0.95,
        "thinking": True,
        "seed": 41,
    }


def test_record_publishes_the_source_and_the_trace(log, directory, tree, attempt):
    """§9.2's two orchestrator-owned files, with their bytes."""
    _, campaign, _ = tree
    log.record(attempt)
    files = directory.files(campaign, attempt.node_id)
    assert set(files) == {SOURCE_FILENAME, TRACE_FILENAME}
    assert files[SOURCE_FILENAME].decode("utf-8") == SOURCE
    trace = json.loads(files[TRACE_FILENAME])
    assert trace["node_id"] == attempt.node_id
    assert trace["campaign_id"] == campaign
    assert trace["code_hash"] == attempt.code_hash
    assert trace["fail_class"] == "ok"


def test_the_row_address_is_the_directory_the_bytes_landed_in(
    log, directory, tree, attempt
):
    """One path resolved once — the two halves cannot disagree.

    This is the property §9.1's ``artifact_uri TEXT NOT NULL`` exists to
    keep: a node whose row points at a directory other than the one its
    bytes are in is a node whose numbers cannot be re-derived.
    """
    database_url, _, _ = tree
    record = log.record(attempt)
    row = _row(database_url, attempt.node_id)
    assert record.artifact_uri == row[ARTIFACT_URI_COLUMN]
    assert urlparse(record.artifact_uri).path == str(
        directory.node_directory(attempt.campaign_id, attempt.node_id)
    )


def test_record_answers_the_files_the_directory_actually_holds(
    log, directory, tree, attempt
):
    """Read back after the commit, not remembered from the staging."""
    _, _, _ = tree
    record = log.record(attempt)
    assert record.artifact_files == (SOURCE_FILENAME, TRACE_FILENAME)


def test_record_keeps_measured_files_the_caller_staged_first(
    log, directory, tree, attempt
):
    """Step 12's five are the caller's; the commit publishes them with ours.

    The evaluator renders the measured five into the node's directory and
    this feature publishes the whole staged set at its commit point, so a
    caller that staged them before recording sees them in the answer —
    without this module ever reading, rendering or re-deriving one.
    """
    _, campaign, _ = tree
    for name in MEASURED_FILES:
        directory.write(campaign, attempt.node_id, name, b"measured")
    record = log.record(attempt)
    assert set(record.artifact_files) == set(MEASURED_FILES) | {
        SOURCE_FILENAME,
        TRACE_FILENAME,
    }
    assert set(directory.files(campaign, attempt.node_id)) == set(record.artifact_files)


def test_a_retry_keeps_the_published_measured_files(log, directory, tree, attempt):
    """The whole-directory commit must not delete step 12's five numbers.

    §9.2's seven files have two owners and feature 240 publishes the
    directory.  A retry of an *evaluated* node — feature 244's re-run, or
    a §14 reclamation — therefore re-publishes the standing attempt's
    artifact, and without the carry-forward it would replace the
    directory with two files and silently drop every number the
    evaluation produced.

    The starting state is the one a completed step 12 leaves: a published
    directory holding all seven, and an empty staging area.  It is built
    here directly — all seven staged together, one commit — rather than
    by calling this feature twice, because the composed path reaches it
    the same way: the evaluator's write path stages its five *and*
    feature 173's pair into the node's directory and commits once
    (``artifacts.persist_execution`` is that pair, for that reason).  A
    second commit staging only the five would drop the pair, exactly as
    this feature would drop the five.
    """
    _, campaign, _ = tree
    directory.write(campaign, attempt.node_id, SOURCE_FILENAME, attempt.code)
    directory.write(campaign, attempt.node_id, TRACE_FILENAME, b"{}")
    for name in MEASURED_FILES:
        directory.write(campaign, attempt.node_id, name, b"measured")
    directory.commit(campaign, attempt.node_id)
    assert set(directory.files(campaign, attempt.node_id)) == set(
        MEASURED_FILES
    ) | {SOURCE_FILENAME, TRACE_FILENAME}
    assert directory.staged(campaign, attempt.node_id) == {}

    # The first record: the row is appended and the five must survive its
    # commit — a commit that staged only the pair would drop them here.
    first = log.record(attempt)
    assert first.appended is True
    assert set(first.artifact_files) == set(MEASURED_FILES) | {
        SOURCE_FILENAME,
        TRACE_FILENAME,
    }
    # The retry: the row is refreshed and the directory re-published.
    record = log.record(attempt)
    assert record.appended is False
    assert set(directory.files(campaign, attempt.node_id)) == set(
        MEASURED_FILES
    ) | {SOURCE_FILENAME, TRACE_FILENAME}
    for name in MEASURED_FILES:
        assert directory.files(campaign, attempt.node_id)[name] == b"measured"


def test_the_carry_forward_preserves_the_bytes_exactly(
    log, directory, tree, signal, provenance
):
    """Opaque bytes: nothing decodes, validates or re-renders one.

    A measured file is the artifacts member's business and this module
    cannot read a Parquet file at all — so what is asserted is byte
    identity, which is the only property the orchestrator is in a
    position to guarantee.
    """
    _, campaign, _ = tree
    first = Attempt.from_signal(signal, provenance)
    blob = bytes(range(256)) * 4  # not text, not JSON, not any format here
    log.record(first)
    # Step 12's pass: the five measured files staged alongside the pair
    # that is already published, then one commit.
    for name in MEASURED_FILES:
        directory.write(campaign, first.node_id, name, b"placeholder")
    directory.write(campaign, first.node_id, "signal_returns.parquet", blob)
    directory.commit(campaign, first.node_id)
    log.record(first)
    assert (
        directory.files(campaign, first.node_id)["signal_returns.parquet"] == blob
    )


class _FourMethods:
    """The seam's four **required** methods, and deliberately neither optional one.

    The degraded deployment the Protocol's optional pair exists for: a
    store that speaks the write half of the seam and offers no way to
    enumerate or read back what it published.  It is a real shape rather
    than a hypothetical — the seam is satisfied *structurally*, so a store
    written before the carry-forward existed is exactly this object, and
    so is any double a caller injects for a write-only path.
    """

    def __init__(self, store) -> None:
        self._store = store

    def node_directory(self, campaign_id, node_id):
        return self._store.node_directory(campaign_id, node_id)

    def write(self, campaign_id, node_id, filename, data):
        return self._store.write(campaign_id, node_id, filename, data)

    def commit(self, campaign_id, node_id):
        return self._store.commit(campaign_id, node_id)

    def discard(self, campaign_id, node_id):
        return self._store.discard(campaign_id, node_id)


def test_a_store_without_the_optional_pair_still_records_the_attempt(
    tree, attempt, tmp_path
):
    """A degraded artifact, never a failed write.

    The row, the source and the trace are feature 240's sentence.  A store
    that cannot hand back a published Parquet file must not turn that into
    a refusal — the caller that wants the measured five preserved stages
    them itself, which needs no recovery at all.  The record is complete
    for what this feature owns; only the *carry* is skipped.
    """
    from pathlib import Path as _Path

    database_url, campaign, _ = tree
    store = MemoryDirectory(tmp_path / "artifacts")
    log = AttemptLog(database_url, _FourMethods(store))
    first = log.record(attempt)
    assert first.appended is True
    second = log.record(attempt)
    assert second.appended is False
    assert set(store.files(campaign, attempt.node_id)) == {
        SOURCE_FILENAME,
        TRACE_FILENAME,
    }
    assert _Path(store.node_directory(campaign, attempt.node_id)).is_dir()


def test_a_store_exposing_only_one_of_the_optional_pair_is_not_refused(
    tree, attempt, tmp_path
):
    """The two are asked for *together*, so half of one is none of it.

    ``files`` is useless without ``read`` and ``read`` is unusable without
    ``files`` — the carry-forward asks for the pair in one ``callable``
    check rather than nesting two.  A store offering one is treated
    exactly like :class:`_FourMethods`: the attempt is recorded, the carry
    is skipped, and nothing raises.
    """
    database_url, _, _ = tree
    store = MemoryDirectory(tmp_path / "artifacts")

    class _FilesOnly(_FourMethods):
        """``files`` but no ``read`` — enumerable, unreadable."""

        def files(self, campaign_id, node_id):
            return self._store.files(campaign_id, node_id)

    log = AttemptLog(database_url, _FilesOnly(store))
    assert log.record(attempt).appended is True


def test_a_read_that_fails_after_the_name_was_listed_is_not_a_failed_write(
    tree, attempt, tmp_path
):
    """The store disagrees with itself and the attempt is still recorded.

    ``files`` said the name was published and ``read`` then could not
    produce it — a real inconsistency, and the branch that proves the
    guard's *shape*: the caller must not see it as a refusal, because the
    attempt's own two files did publish and the row is written.  This is
    the branch a bare-``Exception`` probe over ``read`` would have
    swallowed as "absent" without ever distinguishing the two, which is
    why the seam asks :meth:`files` first.
    """
    from pathlib import Path as _Path

    database_url, campaign, _ = tree
    store = MemoryDirectory(tmp_path / "artifacts")

    class _Liar(_FourMethods):
        """Lists a measured file, then refuses to hand it back."""

        def files(self, campaign_id, node_id):
            return (*MEASURED_FILES, SOURCE_FILENAME, TRACE_FILENAME)

        def read(self, campaign_id, node_id, filename):
            raise OSError(f"the backend lost {filename}")

    log = AttemptLog(database_url, _Liar(store))
    record = log.record(attempt)
    assert record.appended is True
    # The pair this feature owns published, and only the five it could not
    # recover are missing — a fabricated placeholder would be worse.
    assert record.artifact_files == (SOURCE_FILENAME, TRACE_FILENAME)
    assert _Path(store.node_directory(campaign, attempt.node_id)).is_dir()


def test_a_files_that_fails_outright_is_not_a_failed_write(tree, attempt, tmp_path):
    """The other half of the inconsistency, refused as quietly.

    A store that raises from ``files`` cannot be asked what it published,
    which is the same position as one that never offered ``files`` at all
    — so the carry is skipped on the first question rather than the
    second, and the attempt is recorded by the same path.
    """
    database_url, _, _ = tree
    store = MemoryDirectory(tmp_path / "artifacts")

    class _Unenumerable(_FourMethods):
        """``read`` is real; ``files`` is a store fault."""

        def files(self, campaign_id, node_id):
            raise sqlite3.OperationalError("the index is gone")

        def read(self, campaign_id, node_id, filename):
            return b"unreachable"

    log = AttemptLog(database_url, _Unenumerable(store))
    record = log.record(attempt)
    assert record.appended is True
    assert record.artifact_files == (SOURCE_FILENAME, TRACE_FILENAME)


def test_the_carry_forward_does_not_invent_a_measured_file(log, directory, tree, attempt):
    """Nothing to recover and nothing staged publishes the pair, not seven.

    A placeholder would be a fabricated measured number, which is worse
    than an absent one — the same direction ``0117`` refuses a fabricated
    identity.
    """
    record = log.record(attempt)
    assert record.artifact_files == (SOURCE_FILENAME, TRACE_FILENAME)


def test_record_leaves_nothing_staged(log, directory, tree, attempt):
    """The commit is the commit point: nothing is left half-published."""
    _, campaign, _ = tree
    log.record(attempt)
    assert directory.staged(campaign, attempt.node_id) == {}


def test_record_is_idempotent_by_the_derived_identity(log, directory, tree, attempt):
    """A second write of one attempt refreshes rather than duplicates."""
    database_url, _, _ = tree
    first = log.record(attempt)
    second = log.record(attempt)
    assert first.appended is True
    assert second.appended is False
    with closing(sqlite3.connect(_path_of(database_url))) as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM node WHERE id = ?", (attempt.node_id,)
        ).fetchone()[0]
    assert count == 1


def test_a_retry_refreshes_the_standing_attempt_row(log, directory, tree, signal, provenance):
    """§14's idempotence, on the tree's side.

    Feature 244 re-runs a job and hands over a *new* attempt value — more
    interruptions, an updated class — and the derived identity means it
    lands on the very row the first run wrote. The row describes the
    standing attempt; the artifact's trace describes what it cost.
    """
    database_url, campaign, _ = tree
    first = Attempt.from_signal(
        signal, provenance, error=WorkerInterrupted("reclaimed slot 0")
    )
    log.record(first)
    later = Attempt.from_signal(
        signal,
        provenance,
        attempt=2,
        interruptions=(
            {"slot": 0, "error_class": "WorkerInterrupted", "error_message": "reclaimed"},
        ),
    )
    record = log.record(later)
    assert record.appended is False
    assert record.node_id == first.node_id
    row = _row(database_url, later.node_id)
    assert row["fail_class"] == "ok"
    trace = json.loads(directory.files(campaign, later.node_id)[TRACE_FILENAME])
    assert trace["attempts"] == 2
    assert trace["interruptions"][0]["error_class"] == "WorkerInterrupted"


def test_a_refresh_does_not_blank_step_12s_measured_metrics(
    log, tree, signal, provenance
):
    """The one interaction the refresh's SET clause could get wrong.

    §6.1 step 12 writes the seven §9.1 metrics into this same row, and
    feature 240's refresh runs *after* it — a retry of an evaluated node
    re-writes the attempt's descriptions over a row that already carries
    measured numbers.  So the ``UPDATE`` must name only the columns an
    attempt knows: a ``SET`` built from the table's columns instead of
    from :data:`_ATTEMPT_COLUMNS` would set every metric to ``NULL`` and
    silently delete an evaluation's numbers from the tree, which is the
    tree-side twin of the artifact-side loss the carry-forward prevents.

    The metrics are written here by direct ``UPDATE``, because step 12 is
    feature 363's call and this member must not grow a second writer for
    them just to test that it leaves them alone.
    """
    database_url, _, _ = tree
    log.record(Attempt.from_signal(signal, provenance))
    metrics = {
        "ic_mean": 0.041,
        "ic_tstat": 3.2,
        "ir_standalone": 1.1,
        "ir_marginal": 0.35,
        "turnover": 0.18,
        "cost_adjusted_ir": 0.92,
        "perturb_stability": 0.77,
    }
    with closing(sqlite3.connect(_path_of(database_url))) as connection, connection:
        connection.execute(
            f"UPDATE node SET {', '.join(f'{name} = ?' for name in metrics)} "
            "WHERE id = ?",
            (*metrics.values(), signal.node_id),
        )

    # Feature 244's retry of the same node: an interruption, then the run
    # that stood.
    log.record(
        Attempt.from_signal(
            signal, provenance, error=WorkerInterrupted("reclaimed slot 0")
        )
    )
    record = log.record(
        Attempt.from_signal(
            signal,
            provenance,
            attempt=2,
            interruptions=(
                {
                    "slot": 0,
                    "error_class": "WorkerInterrupted",
                    "error_message": "reclaimed",
                },
            ),
        )
    )
    assert record.appended is False
    assert _row(database_url, signal.node_id)["fail_class"] == "ok"
    row = _row(database_url, signal.node_id)
    for name, value in metrics.items():
        assert row[name] == pytest.approx(value), name


def test_a_second_record_appends_no_second_row_for_the_campaign(
    log, tree, attempt
):
    """The tree's node count is the number of *attempts*, not of calls."""
    database_url, campaign, _ = tree
    log.record(attempt)
    log.record(attempt)
    with closing(sqlite3.connect(_path_of(database_url))) as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM node WHERE campaign_id = ?", (campaign,)
        ).fetchone()[0]
    assert count == 2  # the planted root, plus the one attempt


def test_record_refuses_a_database_without_the_tree(directory, attempt, tmp_path):
    """Named, with the migration that owns the table."""
    empty = f"sqlite:///{tmp_path / 'empty.db'}"
    with pytest.raises(AttemptLogError, match="0118"):
        AttemptLog(directory=directory, database_url=empty).record(attempt)


def test_record_refuses_a_tree_that_does_not_hold_the_parent(
    log, signal, provenance
):
    """The diagnosis names the node; the foreign key is the enforcement."""
    orphan = Attempt(
        parent_id=str(uuid.uuid4()),
        campaign_id=signal.campaign_id,
        theme_root="macro",
        depth=1,
        code=SOURCE,
        code_hash=hashlib.sha256(SOURCE.encode()).hexdigest(),
        stated_mechanism=None,
        provenance=provenance,
    )
    with pytest.raises(AttemptLogError, match="is not in the tree"):
        log.record(orphan)


def test_record_refuses_an_ask_that_is_not_an_attempt(log):
    """The seam's own refusal, for a caller that handed over something else."""
    with pytest.raises(AttemptLogError, match="record persists one attempt"):
        log.record("an attempt, surely")


def test_a_refused_attempt_stages_nothing(log, directory, tree, signal, provenance):
    """Nothing is published for an attempt the tree would not take."""
    _, campaign, _ = tree
    orphan = Attempt(
        parent_id=str(uuid.uuid4()),
        campaign_id=campaign,
        theme_root="macro",
        depth=1,
        code=SOURCE,
        code_hash=hashlib.sha256(SOURCE.encode()).hexdigest(),
        stated_mechanism=None,
        provenance=provenance,
    )
    with pytest.raises(AttemptLogError):
        log.record(orphan)
    assert directory.staged(campaign, orphan.node_id) == {}
    assert directory.commits == []


def test_a_failing_pair_rolls_the_staged_set_back(tree, directory, attempt):
    """A half-written pair is discarded rather than published.

    And the disk is not the whole of the half state — the *row* is the
    other half, and it is deliberately the third assertion here rather
    than a fact left to the docstring.  The row write lands before any
    byte is staged (the ordering fact the sibling test above states from
    the caller's side), so a staging failure leaves a committed row whose
    ``artifact_uri`` names a directory that was never published.  That is
    recoverable rather than corrupt: re-issuing derives the same node, so
    the retry refreshes that row and publishes the directory it names.
    The last three lines are that recovery, run rather than asserted about.
    """
    database_url, campaign, _ = tree
    log = AttemptLog(database_url, RefusingDirectory(directory.root, TRACE_FILENAME))
    with pytest.raises(OSError, match="exec_trace.json"):
        log.record(attempt)
    assert directory.staged(campaign, attempt.node_id) == {}
    assert directory.commits == []
    assert directory.files(campaign, attempt.node_id) == {}
    assert _row(database_url, attempt.node_id)["artifact_uri"]

    # The identity law is what makes the half state recoverable: the
    # second call is the *same* node, so it publishes what the first
    # could not, and the tree's count stays the number of attempts.
    record = AttemptLog(database_url, directory).record(attempt)
    assert record.appended is False, "the retry refreshes, it does not append"
    assert set(record.artifact_files) == {SOURCE_FILENAME, TRACE_FILENAME}
    with closing(sqlite3.connect(_path_of(database_url))) as connection:
        rows = connection.execute(
            "SELECT COUNT(*) FROM node WHERE id = ?", (attempt.node_id,)
        ).fetchone()[0]
    assert rows == 1


def test_a_row_write_refusal_leaves_the_callers_staged_set_alone(
    tree, directory, signal, provenance
):
    """The discard is this call's business, not the caller's staged set.

    The row write happens *before* a byte is staged, so a tree refusal
    must not reach for the seam's ``discard`` — that would throw away the
    measured five the caller staged for the node before recording, which
    are none of this call's business to destroy.  This is the ordering
    fact: refusal, then staging.
    """
    _, campaign, _ = tree
    orphan = Attempt(
        parent_id=str(uuid.uuid4()),
        campaign_id=campaign,
        theme_root="macro",
        depth=1,
        code=SOURCE,
        code_hash=hashlib.sha256(SOURCE.encode()).hexdigest(),
        stated_mechanism=None,
        provenance=provenance,
    )
    for name in MEASURED_FILES:
        directory.write(campaign, orphan.node_id, name, b"measured")
    log = AttemptLog(tree[0], directory)
    with pytest.raises(AttemptLogError, match="is not in the tree"):
        log.record(orphan)
    assert set(directory.staged(campaign, orphan.node_id)) == set(MEASURED_FILES)
    assert directory.discards == []


def test_the_log_refuses_a_store_that_does_not_speak_the_seam(tree):
    """The four methods, named — a wiring fault must not wait for an attempt."""
    database_url, _, _ = tree
    with pytest.raises(AttemptLogError, match="node_directory"):
        AttemptLog(database_url, SeamlessDirectory())


def test_the_log_refuses_a_blank_database_url(directory):
    """A log with no tree names no table its rows could reach."""
    with pytest.raises(AttemptLogError, match="needs a database URL"):
        AttemptLog("   ", directory)


def test_the_log_refuses_a_sqlite_url_with_a_host(directory):
    """The grammar this member speaks is a file, not a server."""
    with pytest.raises(AttemptLogError, match="must not carry a host"):
        _ = AttemptLog("sqlite://example.com/tree.db", directory).path


def test_the_log_refuses_a_non_sqlite_url(directory):
    """The spec's SQLite allowance, refused by name rather than by driver."""
    with pytest.raises(AttemptLogError, match="unsupported"):
        _ = AttemptLog("postgresql://localhost/nullius", directory).path


def test_the_log_refuses_an_in_memory_tree(directory):
    """A node row must outlive the attempt that wrote it."""
    with pytest.raises(AttemptLogError, match="no database path"):
        _ = AttemptLog("sqlite:///:memory:", directory).path


def test_the_url_is_translated_on_first_use_not_at_construction(directory):
    """Composition-time work performs no I/O — the store's own contract.

    The tree is a fact about the deployment and constructing a log must
    not touch the disk for it: a factory builds every registered
    component on every ``create_app()`` call, and a constructor that
    translated the URL eagerly would be resolving a path at import of a
    deployment whose database does not exist yet.
    """
    log = AttemptLog("sqlite:///never-opened.db", directory)
    assert log.database_url == "sqlite:///never-opened.db"
    assert not Path("never-opened.db").exists()


class TestTheCarryForwardAgainstTheRealStore:
    """The same scenario through the artifacts member's own store.

    Everything else in this file runs against :class:`MemoryDirectory`,
    which is a double written to the seam's *documented* contract.  This
    class is the check on that double: the carry-forward's whole reason
    for existing is that a real ``commit`` replaces the node's directory
    wholesale, so a double that merged instead would pass every test above
    while the deployment lost step 12's five numbers.  Driving the real
    :class:`artifacts.ArtifactStore` is what makes the claim about the
    contract rather than about the fake.

    The store is imported in-function and by path, the same bootstrap the
    cross-member suite uses: this member may not import the sibling, and a
    workspace without it should lose these tests and nothing else.
    """

    @staticmethod
    def _store(tmp_path: Path):
        src = REPO_ROOT / "packages" / "artifacts" / "src"
        if str(src) not in sys.path:
            sys.path.insert(0, str(src))
        artifacts = pytest.importorskip(
            "artifacts", reason="the artifacts member is not in this workspace"
        )
        return artifacts.ArtifactStore(tmp_path / "artifacts")

    def test_a_retry_keeps_the_measured_files_through_a_real_commit(
        self, tree, attempt, tmp_path
    ):
        database_url, campaign, _ = tree
        store = self._store(tmp_path)
        log = AttemptLog(database_url, store)

        # The published state step 12 leaves: all seven in one commit.  The
        # artifact store keeps no knowledge of the tree, so a published
        # directory beside an unwritten row is an ordinary state — the two
        # halves of the pipeline's step 12 are written by different
        # members and neither is first.  (For this feature the *row* is
        # what `appended` tracks, so the first `record` here appends it.)
        store.write(campaign, attempt.node_id, SOURCE_FILENAME, attempt.code)
        store.write(campaign, attempt.node_id, TRACE_FILENAME, "{}")
        for name in MEASURED_FILES:
            store.write(campaign, attempt.node_id, name, b"measured")
        store.commit(campaign, attempt.node_id)
        assert set(store.files(campaign, attempt.node_id)) == set(
            MEASURED_FILES
        ) | {SOURCE_FILENAME, TRACE_FILENAME}

        # The first record appends the row and must carry the five across
        # its own commit rather than replacing the directory with two.
        first = log.record(attempt)
        assert first.appended is True
        assert set(first.artifact_files) == set(MEASURED_FILES) | {
            SOURCE_FILENAME,
            TRACE_FILENAME,
        }
        # The retry refreshes the row and re-publishes — the case the
        # carry-forward exists for.
        second = log.record(attempt)
        assert second.appended is False
        assert set(second.artifact_files) == set(MEASURED_FILES) | {
            SOURCE_FILENAME,
            TRACE_FILENAME,
        }
        # The bytes, not merely the names — an opaque carry that
        # re-rendered or re-encoded would pass a name-only check.
        for name in MEASURED_FILES:
            assert store.read(campaign, attempt.node_id, name) == b"measured"
        assert store.read(campaign, attempt.node_id, TRACE_FILENAME)

    def test_a_fresh_record_against_the_real_store_publishes_the_pair(
        self, tree, attempt, tmp_path
    ):
        database_url, campaign, _ = tree
        store = self._store(tmp_path)
        record = AttemptLog(database_url, store).record(attempt)
        assert record.artifact_files == (SOURCE_FILENAME, TRACE_FILENAME)
        assert store.has_node(campaign, attempt.node_id)

    def test_the_real_store_actually_replaces_wholesale(self, tree, attempt, tmp_path):
        """The fact the carry-forward exists for, asserted rather than assumed.

        If a future artifacts member changed ``commit`` to *merge* the
        staged set into the published directory, the carry-forward would
        become harmless rather than necessary — and this test is what
        would say so, instead of leaving a reader to wonder why the
        restaging is there.
        """
        _, campaign, _ = tree
        store = self._store(tmp_path)
        store.write(campaign, attempt.node_id, SOURCE_FILENAME, "first")
        store.commit(campaign, attempt.node_id)
        store.write(campaign, attempt.node_id, TRACE_FILENAME, "second")
        store.commit(campaign, attempt.node_id)
        assert set(store.files(campaign, attempt.node_id)) == {TRACE_FILENAME}


# -- Including failures ---------------------------------------------------------------


def test_a_timeout_is_persisted_like_any_other_attempt(log, tree, signal, provenance):
    """The feature's clause: a failure is written by the same call.

    §5.2's kill arrives as a *stated* class, which is how the sandbox
    reports it — the run is hard-killed and its class returned as a value,
    never raised.
    """
    database_url, _, _ = tree
    built = Attempt.from_signal(
        signal,
        provenance,
        fail_class="timeout",
        error=RuntimeError("hard-killed at the 30s wall"),
    )
    record = log.record(built)
    assert record.fail_class == "timeout"
    row = _row(database_url, built.node_id)
    assert row["fail_class"] == "timeout"
    assert row["code_hash"] == built.code_hash
    assert row[ARTIFACT_URI_COLUMN] == record.artifact_uri


def test_a_failed_attempt_publishes_its_artifact_too(log, directory, tree, signal, provenance):
    """Its source and its trace, exactly as a success's.

    A failure's directory is *not* empty: the attempt ran, the source is
    the one that ran, and the trace is the record of how it ended — which
    is the whole of what 'with its full artifact, including failures'
    means for an attempt whose evaluation never produced a number.
    """
    _, campaign, _ = tree
    built = Attempt.from_signal(signal, provenance, error=RuntimeError("sandbox died"))
    log.record(built)
    files = directory.files(campaign, built.node_id)
    assert files[SOURCE_FILENAME].decode("utf-8") == SOURCE
    trace = json.loads(files[TRACE_FILENAME])
    assert trace["fail_class"] == "error"
    assert trace["error_class"] == "RuntimeError"
    assert trace["error_message"] == "sandbox died"


def test_a_tripwire_failure_records_its_class_and_evidence(log, tree, signal, provenance):
    """§9.1's fourth class, from a caller that knows it."""
    database_url, _, _ = tree
    built = Attempt.from_signal(
        signal, provenance, fail_class="tripwire_fail", error=RuntimeError("peeked at holdout")
    )
    log.record(built)
    row = _row(database_url, built.node_id)
    assert row["fail_class"] == "tripwire_fail"


def test_an_interruption_is_recorded_as_error_with_its_marker(log, tree, signal, provenance):
    """The column answers *how*, the trace answers *to what?*."""
    database_url, campaign, _ = tree
    built = Attempt.from_signal(signal, provenance, error=WorkerInterrupted("reclaimed"))
    log.record(built)
    row = _row(database_url, built.node_id)
    assert row["fail_class"] == "error"
    trace = json.loads(log.directory.files(campaign, built.node_id)[TRACE_FILENAME])
    assert trace["error_class"] == "WorkerInterrupted"


def test_the_trace_carries_the_whole_retry_history(log, directory, tree, signal, provenance):
    """The table holds one node; the artifact holds what it cost."""
    _, campaign, _ = tree
    built = Attempt.from_signal(
        signal,
        provenance,
        attempt=2,
        interruptions=(
            {"slot": 0, "error_class": "WorkerInterrupted", "error_message": "reclaimed"},
        ),
    )
    log.record(built)
    trace = json.loads(directory.files(campaign, built.node_id)[TRACE_FILENAME])
    assert trace["attempt"] == 2
    assert trace["attempts"] == 2
    assert trace["interruptions"] == [
        {"slot": 0, "error_class": "WorkerInterrupted", "error_message": "reclaimed"}
    ]


# -- A batch -----------------------------------------------------------------------


def test_record_all_persists_every_attempt_in_order(
    log, tree, signal, provenance, plant_root
):
    """A batch of successful and failed attempts, all recorded."""
    database_url, campaign, _ = tree
    second_parent = _plant_sibling(plant_root, campaign)
    second = RefinedSignal(
        node_id=attempt_node_id(second_parent),
        parent_id=second_parent,
        campaign_id=campaign,
        theme_root="macro",
        depth=1,
        code="def signal(ctx):\n    return ctx.volume\n",
        code_hash=hashlib.sha256(b"def signal(ctx):\n    return ctx.volume\n").hexdigest(),
        stated_mechanism=None,
    )
    first = Attempt.from_signal(
        signal,
        provenance,
        fail_class="timeout",
        error=RuntimeError("hard-killed at the 30s wall"),
    )
    third = Attempt.from_signal(
        second, provenance, fail_class="tripwire_fail", error=RuntimeError("peeked")
    )
    records = log.record_all([first, third])
    assert [record.fail_class for record in records] == ["timeout", "tripwire_fail"]
    assert records[0].appended is True and records[1].appended is True
    assert _row(database_url, first.node_id)["fail_class"] == "timeout"
    assert _row(database_url, third.node_id)["fail_class"] == "tripwire_fail"


def test_every_attempt_is_logged_including_every_failure_class(
    log, directory, tree, signal, provenance, plant_root
):
    """The feature's sentence, as a *count* rather than as a case.

    The spec's word is **every**, and it is the clause the whole module is
    shaped around: a log that wrote only successes would make an absent
    row ambiguous, because *absent* is already how §9.1's tree says "never
    expanded".  So the assertion is the sharpest form of it — record one
    attempt per §9.1 class, then check that the tree holds exactly four
    rows and the store holds exactly four directories, each with its
    artifact.  A writer that silently dropped a class would fail here even
    if every per-case test above still passed.

    ``tripwire_fail`` is the one class no caller can *infer* — §C6's
    tripwires raise an exception that is indistinguishable from any other
    at this seam, so the caller that ran the tripwire states the class.
    That is why :func:`classify_failure` accepts a stated word as well as
    an exception, and this test is where the two paths meet.
    """
    database_url, campaign, _ = tree

    def _signal(parent: str, body: str) -> RefinedSignal:
        return RefinedSignal(
            node_id=attempt_node_id(parent),
            parent_id=parent,
            campaign_id=campaign,
            theme_root="macro",
            depth=1,
            code=body,
            code_hash=hashlib.sha256(body.encode()).hexdigest(),
            stated_mechanism=None,
        )

    # Four attempts need four *parents*, not four bodies: an attempt's node
    # identity is derived from its parent alone (feature 239's
    # ``refined_node_id``), so two attempts expanding one parent are one
    # node — the second would refresh the first rather than append a row.
    # Four parents is what four rows requires, and the ``body`` differs per
    # parent only so no two attempts share a ``code_hash``.
    parents = (signal.parent_id,) + tuple(
        _plant_sibling(plant_root, campaign) for _ in range(3)
    )
    bodies = (
        "def signal(ctx):\n    return ctx.close\n",
        "def signal(ctx):\n    return ctx.volume\n",
        "def signal(ctx):\n    return ctx.open\n",
        "def signal(ctx):\n    return ctx.high\n",
    )
    roots = tuple(
        signal if parent == signal.parent_id else _signal(parent, body)
        for parent, body in zip(parents, bodies, strict=True)
    )
    attempts = (
        Attempt.from_signal(roots[0], provenance),  # ok
        Attempt.from_signal(
            roots[1],
            provenance,
            fail_class="timeout",
            error=RuntimeError("hard-killed at the 30s wall"),
        ),
        Attempt.from_signal(roots[2], provenance, error=RuntimeError("died")),
        Attempt.from_signal(
            roots[3],
            provenance,
            fail_class="tripwire_fail",
            error=RuntimeError("peeked at the holdout"),
        ),
    )

    records = log.record_all(attempts)

    assert [record.fail_class for record in records] == list(FAIL_CLASSES)
    # One row per attempt — not one per *successful* attempt.  Scoped to
    # the four the call was handed: the fixture's planted parents are rows
    # in this campaign too, and counting the whole campaign would make the
    # assertion pass for the wrong reason the moment a fixture changed.
    with closing(sqlite3.connect(_path_of(database_url))) as connection:
        marks = ",".join("?" * len(attempts))
        rows = connection.execute(
            f"SELECT id, fail_class FROM node WHERE id IN ({marks})",
            tuple(attempt.node_id for attempt in attempts),
        ).fetchall()
    assert dict(rows) == {a.node_id: a.fail_class for a in attempts}
    assert len(rows) == len(FAIL_CLASSES)
    # And one published directory per attempt, each holding its artifact —
    # a failure's directory is not empty.
    for record, attempt in zip(records, attempts, strict=True):
        assert record.node_id == attempt.node_id
        published = directory.files(campaign, attempt.node_id)
        assert set(published) == {SOURCE_FILENAME, TRACE_FILENAME}
        assert json.loads(published[TRACE_FILENAME])["fail_class"] == attempt.fail_class
        assert _row(database_url, attempt.node_id)["fail_class"] == attempt.fail_class


def test_record_all_of_nothing_records_nothing(log):
    """Nothing to persist is not this verb's judgement to overturn."""
    assert log.record_all([]) == ()


def test_record_all_refuses_a_bare_string(log):
    """An ask spelled without its brackets must not become a batch of characters."""
    with pytest.raises(AttemptLogError, match="batch of attempts"):
        log.record_all(SOURCE)


def test_record_all_refuses_a_non_iterable(log):
    """Same refusal, from the other side."""
    with pytest.raises(AttemptLogError, match="batch of attempts"):
        log.record_all(42)


def test_record_all_stops_at_the_refusal_it_meets(
    log, tree, signal, provenance, plant_root
):
    """An attempt the tree refuses stops the batch rather than being skipped.

    The attempts before it are whole — one transaction, one published
    directory each — and the derived identity makes re-issuing the batch
    refresh them rather than duplicate them, so the campaign loop finishes
    a log the first run started.
    """
    database_url, campaign, _ = tree
    good = Attempt.from_signal(signal, provenance)
    orphan = Attempt(
        parent_id=str(uuid.uuid4()),
        campaign_id=campaign,
        theme_root="macro",
        depth=1,
        code=SOURCE,
        code_hash=hashlib.sha256(SOURCE.encode()).hexdigest(),
        stated_mechanism=None,
        provenance=provenance,
    )
    with pytest.raises(AttemptLogError, match="is not in the tree"):
        log.record_all([good, orphan])
    assert _row(database_url, good.node_id)["campaign_id"] == campaign

    # The docstring's load-bearing claim: the half-written batch is
    # *idempotent, not destructive*.  §6.1's campaign loop that stopped at
    # this refusal runs again — and the second run re-issues the same two
    # attempts against a tree the first run already has one of.  The
    # derived identity is what makes that safe: the same attempt is the
    # same node, so the second call refreshes the row the first wrote and
    # appends only the one that had been refused.  Two calls, two rows —
    # the count is the number of *attempts*, not of calls, which is §14's
    # idempotence read off the tree rather than asserted about the code.
    planted = _plant_sibling(plant_root, campaign)
    orphan = Attempt(
        parent_id=planted,
        campaign_id=campaign,
        theme_root="macro",
        depth=1,
        code=SOURCE,
        code_hash=hashlib.sha256(SOURCE.encode()).hexdigest(),
        stated_mechanism=None,
        provenance=provenance,
    )
    records = log.record_all([good, orphan])
    assert [record.node_id for record in records] == [
        good.node_id,
        orphan.node_id,
    ]
    # Re-issuing is the refresh, not a second insert: one row per attempt.
    assert _row(database_url, good.node_id)["parent_id"] == good.parent_id
    assert _row(database_url, orphan.node_id)["parent_id"] == planted
    with closing(sqlite3.connect(_path_of(database_url))) as connection:
        rows = connection.execute(
            "SELECT COUNT(*) FROM node WHERE id IN (?, ?)",
            (good.node_id, orphan.node_id),
        ).fetchone()[0]
    assert rows == 2, (
        "re-issuing the batch after the refusal must refresh the attempts "
        "the first run landed rather than insert them a second time; "
        "§14's idempotence is the derived identity doing the work"
    )


def test_record_attempts_resolves_the_tree_from_the_environment(
    tree, directory, attempt, monkeypatch
):
    """The module-level spelling, reading ``DATABASE_URL`` like every store."""
    database_url, _, _ = tree
    monkeypatch.setenv("DATABASE_URL", database_url)
    records = record_attempts([attempt], directory=directory)
    assert len(records) == 1
    assert records[0].node_id == attempt.node_id


def test_record_attempts_prefers_its_explicit_url(tree, directory, attempt, monkeypatch):
    """An explicit tree is not the ambient one."""
    database_url, _, _ = tree
    monkeypatch.setenv("DATABASE_URL", "sqlite:///nope.db")
    assert record_attempts([attempt], directory=directory, database_url=database_url)


def test_record_attempts_refuses_an_unnamed_tree(directory, attempt, monkeypatch):
    """Feature 240's sentence needs a tree named: a silent skip is the refusal."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(AttemptLogError, match="nothing names a tree"):
        record_attempts([attempt], directory=directory)


def test_record_attempts_refuses_an_empty_database_url(
    directory, attempt, monkeypatch
):
    """A blank value is an unset one — the store's own reading."""
    monkeypatch.setenv("DATABASE_URL", "   ")
    with pytest.raises(AttemptLogError, match="nothing names a tree"):
        record_attempts([attempt], directory=directory)


def test_record_attempts_takes_an_explicit_env(directory, tree, attempt):
    """The injected environment, for a caller that holds one."""
    database_url, _, _ = tree
    records = record_attempts(
        [attempt], directory=directory, env={"DATABASE_URL": database_url}
    )
    assert len(records) == 1


# -- The widened tree is not required -----------------------------------------------


def test_the_writer_serves_a_tree_at_0118_alone(
    database_url, migrate_at, directory, campaign_id, plant_root, provenance
):
    """A chain whose widenings have not run still takes the attempt.

    ``0118`` alone declares five structural columns; ``0117``'s
    ``code_hash`` / ``artifact_uri`` pair and every column after it are
    absent.  The INSERT names the intersection of what an attempt carries
    with what the table has, which is what lets one writer serve both a
    migration tree that stops at ``0118`` and one that runs through
    ``0117`` — the choice the providers member's node writer states from
    the other side.  What is *not* written here is that the attempt is
    incomplete: the columns the narrow tree has still land, and the ones
    it has not reached are simply absent from the statement rather than
    replacing the write with a refusal.
    """
    migrate_at(database_url, "0111_campaign_table", "0118_node_table")
    parent = plant_root(campaign_id, depth=0)
    built = Attempt(
        parent_id=parent,
        campaign_id=campaign_id,
        theme_root="macro",
        depth=1,
        code=SOURCE,
        code_hash=hashlib.sha256(SOURCE.encode()).hexdigest(),
        stated_mechanism=None,
        provenance=provenance,
    )
    log = AttemptLog(database_url, directory)
    assert "code_hash" not in _columns(database_url)
    record = log.record(built)
    row = _row(database_url, built.node_id)
    assert record.appended is True
    # The columns the tree never had are still absent from the statement:
    # one writer serves both chains by naming the intersection.
    assert "code_hash" not in _columns(database_url)
    assert set(row) == {
        "id",
        "parent_id",
        "campaign_id",
        "theme_root",
        "depth",
        FAIL_CLASS_COLUMN,
    }
    assert row["theme_root"] == "macro"
    assert row["depth"] == 1
    assert row[FAIL_CLASS_COLUMN] == "ok"


def test_the_writer_adds_fail_class_to_a_tree_that_lacks_it(
    database_url, migrate_at, directory, campaign_id, plant_root, provenance
):
    """§9.1's column is this feature's own; no migration declares it.

    Without it the *"including failures"* clause has nowhere to go: every
    row would look like one that answered.  The probe makes the addition
    idempotent, because SQLite's ``ADD COLUMN`` carries no ``IF NOT
    EXISTS`` and a second connection must not fail on the first one's
    work.
    """
    migrate_at(database_url, "0111_campaign_table", "0118_node_table")
    assert FAIL_CLASS_COLUMN not in _columns(database_url)
    parent = plant_root(campaign_id, depth=0)
    built = Attempt(
        parent_id=parent,
        campaign_id=campaign_id,
        theme_root="macro",
        depth=1,
        code=SOURCE,
        code_hash=hashlib.sha256(SOURCE.encode()).hexdigest(),
        stated_mechanism=None,
        provenance=provenance,
    )
    log = AttemptLog(database_url, directory)
    log.record(built)
    assert FAIL_CLASS_COLUMN in _columns(database_url)
    # A second connection finds it present and alters nothing.
    log.record(built)
    assert _columns(database_url).count(FAIL_CLASS_COLUMN) == 1
    assert _row(database_url, built.node_id)[FAIL_CLASS_COLUMN] == "ok"


def test_the_writer_leaves_a_tree_with_no_node_table_alone(
    tmp_path, migrate_at, directory, attempt
):
    """The absent table is the record's refusal to name, not a CREATE here.

    Issuing the column migration against a missing table would be
    inventing a tree one column wide; the refusal that names ``0118`` is
    the honest answer.
    """
    database_url = f"sqlite:///{tmp_path / 'tree-less.db'}"
    migrate_at(database_url, "0111_campaign_table")
    with pytest.raises(AttemptLogError, match="no node table"):
        AttemptLog(database_url, directory).record(attempt)
    with closing(sqlite3.connect(_path_of(database_url))) as connection:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert "node" not in tables


def test_the_writer_refuses_a_not_null_column_it_cannot_fill(
    database_url, migrate_at, directory, campaign_id, plant_root, provenance
):
    """A column neither the attempt nor a default fills is named, not guessed.

    No shipped migration declares one, so the column is added here to
    stand in for a future one.  The refusal is what keeps a fabricated
    default from becoming identity belonging to a different node — the
    direction ``0117`` refuses a default for.
    """
    migrate_at(database_url, "0111_campaign_table", "0118_node_table")
    with closing(sqlite3.connect(_path_of(database_url))) as connection, connection:
        connection.execute("ALTER TABLE node ADD COLUMN novelty REAL NOT NULL")
    parent = plant_root(campaign_id, depth=0)
    built = Attempt(
        parent_id=parent,
        campaign_id=campaign_id,
        theme_root="macro",
        depth=1,
        code=SOURCE,
        code_hash=hashlib.sha256(SOURCE.encode()).hexdigest(),
        stated_mechanism=None,
        provenance=provenance,
    )
    with pytest.raises(AttemptLogError, match="'novelty'"):
        AttemptLog(database_url, directory).record(built)


def test_a_not_null_column_with_a_default_is_not_refused(
    database_url, migrate_at, directory, campaign_id, plant_root, provenance
):
    """``0118``'s own ``id`` is the case: the database mints it.

    The exemption is load-bearing rather than decorative — a check that
    asked only "is every NOT NULL column filled by the attempt?" would
    report ``id`` as missing on the very DDL ``0118`` declares, and
    refuse a row that writes perfectly well.
    """
    migrate_at(database_url, "0111_campaign_table", "0118_node_table")
    with closing(sqlite3.connect(_path_of(database_url))) as connection, connection:
        connection.execute(
            "ALTER TABLE node ADD COLUMN confidence REAL NOT NULL DEFAULT 0.0"
        )
    parent = plant_root(campaign_id, depth=0)
    built = Attempt(
        parent_id=parent,
        campaign_id=campaign_id,
        theme_root="macro",
        depth=1,
        code=SOURCE,
        code_hash=hashlib.sha256(SOURCE.encode()).hexdigest(),
        stated_mechanism=None,
        provenance=provenance,
    )
    assert AttemptLog(database_url, directory).record(built).appended is True
    assert _row(database_url, built.node_id)["confidence"] == 0.0
