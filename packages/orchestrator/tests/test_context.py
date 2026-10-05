"""Feature 5, the context — the evaluation inputs a live run loads.

additions_spec_live_evaluation.xml, "Orchestrator Member", feature 5:
*System creates the live evaluation inputs with
orchestrator._context.load_evaluation_context(env=None).  It answers an
EvaluationContext, or None when NULLIUS_EVALUATION_CONFIG is unset.*  The
member is wiring over Z0 — the snapshot member seals and mounts, the
cost-model member loads and prices, the evaluator member computes its own
identity — so every test here runs the *real* seam end to end: a genuine
lake with §4.2's layout staged and sealed through
:class:`snapshot.SnapshotService`, a genuine YAML cost model read through
the member's own loader, a genuine identity folded through
:class:`evaluator.EvaluatorService`.  No fake answers for any of the three,
because the feature's whole claim is that the inputs ``_run_pipeline``
assembles can be loaded as they are, stamped with the hashes those very
bytes resolve to.

One test per claim the feature sentence makes:

* **the answer, or None** — an unset (or blank) ``NULLIUS_EVALUATION_CONFIG``
  answers ``None``; a set one answers the frozen
  :class:`~orchestrator._context.EvaluationContext` holding exactly the
  inputs ``_run_pipeline`` assembles — the mounted snapshot and the closes
  read from its own bars, the loaded cost model and its resolved fee
  schedule — stamped with the provenance triple those bytes resolve to
  (the snapshot's manifest hash, the cost model's own folded hash, the
  evaluator service's own identity), plus the epoch, the store address,
  the artifact directory, the seed, and the run parameters (the dates,
  the horizon, the runtime the gate accepted).

* **the file holds seven keys** — ``snapshot_mount``,
  ``evaluation_dates``, ``horizon``, ``seed``, ``epoch_id``,
  ``artifact_dir`` and ``sandbox_runtime``, each refused when missing
  (there is no default) and each refused when malformed; a key outside
  the vocabulary is refused outright, which is what makes the sentence's
  *"The file never holds a credential"* structural rather than stated —
  a sidecar key reference riding under a name the loader would have
  ignored is refused by name.

* **the sandbox gate** — ``sandbox_runtime`` is ``"gvisor"`` or
  ``"unisolated"`` and nothing else; ``"gvisor"`` loads only with the
  ``runsc`` binary on the ``PATH`` the same environment names (a
  scratch directory holding an executable ``runsc`` — no host gVisor
  install is assumed, and none is reached), and without it the load
  raises naming ``isolation_required``; ``"unisolated"`` loads only with
  ``acknowledge_unisolated: true`` beside it.

* **the other inputs come from the variables the members already read**
  — ``DATABASE_URL`` (refused when unset), ``NULLIUS_COST_MODEL_PATH``
  (honoured when set, the shipped §6.2 document when not), and the
  evaluator's own ``NULLIUS_EVALUATOR_IMAGE`` (refused, translated into
  this module's one error, when the identity cannot resolve).  The null
  sidecar's variables are never this module's to read, and no test here
  sets one.

* **the refusals** — a missing file, a missing key, an ``epoch_id`` that
  is not a non-blank string, and every other configured-but-broken
  shape raise :class:`~orchestrator._context.EvaluationConfigError`
  opening with the code word ``evaluation_config`` and naming the key or
  variable at fault.

* **the module's surface** — ``__all__`` names the three exports
  feature 8 re-exports from the package.

No test opens a network connection, reads a real credential, or writes
outside a pytest temporary directory.  The seal's optional manifest
record resolves from the process environment, so the fixture clears
``DATABASE_URL`` first and the lake stays filesystem-only — the manifest
inside the sealed directory is the only record this suite reads.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from cost_model import CostModelConfig, FeeSchedule, load_cost_model
from evaluator import EvaluatorService
from orchestrator._context import (
    EvaluationConfigError,
    EvaluationContext,
    load_evaluation_context,
)
from snapshot import SnapshotMount, SnapshotService

#: The refusal's greppable opening, pinned here from the feature's own
#: parenthetical — *(code word evaluation_config)* — rather than read off
#: the module, so a drifted code word fails a test about the spec text.
CODE_WORD = "evaluation_config"

#: The seven keys the feature sentence names, in its own order.  Spelled
#: here rather than imported, the same discipline ``test_member.py``
#: states for its dependencies: a key dropped or renamed is a failing
#: test about *the feature text*.
CONFIG_KEYS = (
    "snapshot_mount",
    "evaluation_dates",
    "horizon",
    "seed",
    "epoch_id",
    "artifact_dir",
    "sandbox_runtime",
)

#: The world the sealed snapshot carries: three symbols over twelve
#: daily bars, the cross-section and the runway the way the e2e journey
#: stages its own.  The evaluation dates are the interior of the span —
#: the lookback is runway the signal reads, and the tail is the
#: horizon's forward bar, so the grid names only the days a live
#: evaluation would score.
SYMBOLS = ("SYM00", "SYM01", "SYM02")
FIRST_DAY = dt.date(2026, 9, 1)
BAR_DAYS = tuple(FIRST_DAY + dt.timedelta(days=offset) for offset in range(12))
LOOKBACK = 6
EVALUATION_DAYS = tuple(
    day.isoformat() for day in BAR_DAYS[LOOKBACK : LOOKBACK + 4]
)
HORIZON = 1
SEED = 20260924
EPOCH = "epoch-2026-10-05-a"
ARTIFACT_DIR_NAME = "artifacts"

#: The evaluator image the fixture's environment pins — digest-pinned,
#: the only spelling the evaluator member's identity accepts.
IMAGE = "ghcr.io/nullius/evaluator@sha256:" + "ab" * 32

#: The cost model document's own identity: a venue and version no other
#: test in the workspace uses, with two *distinct* rates so a taker that
#: landed in the maker's field cannot pass.
VENUE = "testnet_spot"
VERSION = "2026.10.0"
TAKER_BPS = 12.5
MAKER_BPS = 8.0

#: One symbol's daily closes: a pinned, gently rising path per symbol so
#: every forward return is positive and two symbols never share a price.
def _close(symbol_index: int, day_index: int) -> float:
    return round(100.0 + 10.0 * symbol_index + 0.25 * day_index, 2)


#: The marker for "this key is absent", so a helper can spell both a
#: missing key and a malformed one.
_OMIT = object()


@dataclasses.dataclass(frozen=True)
class LiveWorld:
    """Everything one configured live evaluation is pointed at.

    The sealed lake (through the record the seal answered), the cost
    model document, the configuration file, and the environment that
    names them — the inputs, the file and the environment held together
    so a test that overrides one still sees the other two.
    """

    #: The seal's own record: ``name`` and ``path`` of the sealed snapshot.
    sealed: Any
    #: The service that sealed — the reader the manifest assertions go
    #: through, a different door from the one the loader uses.
    service: SnapshotService
    #: The cost model document the environment points at.
    cost_model_path: Path
    #: The base configuration document (with every key present).
    document: Mapping[str, Any]
    #: The environment the loader is handed: every variable the members
    #: already read, so the load is one environment end to end.
    environment: Mapping[str, str]
    #: The store address, a per-fixture SQLite file no test opens.
    database_url: str
    #: A directory guaranteed to hold no ``runsc``.
    bare_path: Path
    #: A directory holding an executable ``runsc``.
    runsc_path: Path


def _stage_and_seal(
    lake_root: Path,
    bars: Mapping[str, Mapping[dt.date, Sequence[Any]]],
) -> tuple[SnapshotService, Any]:
    """Stage §4.2's layout and seal it through the shipped service.

    Each ``(symbol, day)`` entry is a sequence of close spellings — one
    row each — so the standard world stages one candle per day while a
    content test can stage two rows for one bar and see the loader
    refuse.  Everything else mirrors the e2e journey's staging: the
    partition granularity, the two required columns, and the venue's
    own *string* spelling of a close, which is the thing under test in
    the reader this feeds.
    """
    (lake_root / "snapshots").mkdir(parents=True)
    staging = lake_root / "staging"
    for symbol, series in bars.items():
        for day, closes in series.items():
            partition = (
                staging / "bars" / f"symbol={symbol}" / f"date={day.isoformat()}"
            )
            partition.mkdir(parents=True)
            pq.write_table(
                pa.table(
                    {
                        "symbol": [symbol] * len(closes),
                        "open_time": [
                            dt.datetime.combine(day, dt.time(0), tzinfo=dt.UTC)
                        ]
                        * len(closes),
                        "close": [str(close) for close in closes],
                        "volume": ["12.5"] * len(closes),
                    }
                ),
                partition / "part-0.parquet",
            )
    service = SnapshotService(lake_root)
    sealed = service.seal(sealed_at=dt.datetime(2026, 11, 1, tzinfo=dt.UTC))
    return service, sealed


def _standard_bars() -> dict[str, dict[dt.date, list[float]]]:
    """The world's bars, in *staged* form: the closes of one candle a day.

    One-row lists per symbol-day — the staging shape :func:`_stage_and_seal`
    writes — so a content test can drop a second row for one bar (or a
    poisoned close) and see the read refuse.  The loader's own answer is
    the scalar :func:`_standard_closes`, which is what
    ``context.closes`` is compared against.
    """
    return {
        symbol: {
            day: [_close(index, offset)] for offset, day in enumerate(BAR_DAYS)
        }
        for index, symbol in enumerate(SYMBOLS)
    }


def _standard_closes() -> dict[str, dict[dt.date, float]]:
    """The world's closes as the loader answers them: one close a bar.

    The same pinned path :func:`_standard_bars` stages, flattened to the
    ``{symbol: {bar date: close}}`` shape step 4's ``closes`` argument is
    defined over — the venue's string spelling already parsed to a float.
    """
    return {
        symbol: {day: _close(index, offset) for offset, day in enumerate(BAR_DAYS)}
        for index, symbol in enumerate(SYMBOLS)
    }


def _standard_document(
    snapshot_path: Path, tmp_path: Path
) -> dict[str, Any]:
    """One complete configuration document, pointing at ``snapshot_path``.

    The same seven keys the ``live`` fixture writes, plus the unisolated
    acknowledgement — a standalone builder for the tests that stage their
    own sealed lake (a poisoned close, a duplicate bar, a snapshot with no
    bars) and so cannot use the fixture's environment wholesale.
    """
    return {
        "snapshot_mount": str(snapshot_path),
        "evaluation_dates": list(EVALUATION_DAYS),
        "horizon": HORIZON,
        "seed": SEED,
        "epoch_id": EPOCH,
        "artifact_dir": str(tmp_path / ARTIFACT_DIR_NAME),
        "sandbox_runtime": "unisolated",
        "acknowledge_unisolated": True,
    }


def _environment_over(base: str, document: Mapping[str, Any]) -> dict[str, str]:
    """An environment naming ``document``, rooted at ``base``.

    Writes the document to a fresh file under ``base`` and hands back the
    variables the loader reads before it reaches the snapshot: the
    configuration path, the store, and the pinned evaluator image.  Used
    by the tests that stage their own lake and so cannot borrow the
    fixture's ``LiveWorld`` environment.
    """
    root = Path(base)
    path = root / f"evaluation-{abs(id(document))}.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return {
        "NULLIUS_EVALUATION_CONFIG": str(path),
        "DATABASE_URL": f"sqlite:///{root / 'environment-over.db'}",
        "NULLIUS_EVALUATOR_IMAGE": IMAGE,
    }


@pytest.fixture
def world_none() -> Mapping[str, str]:
    """The unconfigured environment: nothing the loader needs is set.

    An empty mapping stands in for a process whose environment was never
    pointed at an evaluation — the state that answers ``None``.
    """
    return {}


@pytest.fixture
def live(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LiveWorld:
    """One configured live evaluation, staged for real.

    The lake is sealed through the snapshot member's own service, the
    cost model is a genuine YAML document, and the environment names
    both plus the pinned image and the store — nothing is faked, because
    the feature's claim is precisely that these inputs load as they are.
    ``DATABASE_URL`` is cleared from the process environment first so
    the seal's optional manifest record resolves to none and the lake
    stays filesystem-only; the loader itself reads only the mapping it
    is handed.
    """
    monkeypatch.delenv("DATABASE_URL", raising=False)
    bars = _standard_bars()
    service, sealed = _stage_and_seal(tmp_path / "lake", bars)

    cost_model_path = tmp_path / "cost_model.yaml"
    cost_model_path.write_text(
        "# The campaign's cost model — the §6.2 shape the shared library\n"
        "# resolves, with two distinct rates so a swapped field cannot pass.\n"
        "cost_model:\n"
        f'  version: "{VERSION}"\n'
        f"  venue: {VENUE}\n"
        "  fees:\n"
        f"    taker_bps: {TAKER_BPS}\n"
        f"    maker_bps: {MAKER_BPS}\n",
        encoding="utf-8",
    )

    document = {
        "snapshot_mount": str(sealed.path),
        "evaluation_dates": list(EVALUATION_DAYS),
        "horizon": HORIZON,
        "seed": SEED,
        "epoch_id": EPOCH,
        "artifact_dir": str(tmp_path / ARTIFACT_DIR_NAME),
        "sandbox_runtime": "unisolated",
        "acknowledge_unisolated": True,
    }
    config_path = tmp_path / "evaluation.json"
    config_path.write_text(json.dumps(document), encoding="utf-8")

    bare_path = tmp_path / "bare-path"
    bare_path.mkdir()
    runsc_path = tmp_path / "with-runsc"
    runsc_path.mkdir()
    runsc = runsc_path / "runsc"
    runsc.write_text("#! /bin/sh\n", encoding="utf-8")
    runsc.chmod(0o755)

    database_url = f"sqlite:///{tmp_path / 'context-test.db'}"
    environment = {
        "NULLIUS_EVALUATION_CONFIG": str(config_path),
        "DATABASE_URL": database_url,
        "NULLIUS_EVALUATOR_IMAGE": IMAGE,
        "NULLIUS_COST_MODEL_PATH": str(cost_model_path),
        "PATH": str(bare_path),
    }
    return LiveWorld(
        sealed=sealed,
        service=service,
        cost_model_path=cost_model_path,
        document=document,
        environment=environment,
        database_url=database_url,
        bare_path=bare_path,
        runsc_path=runsc_path,
    )


def _config_file(world: LiveWorld, **overrides: Any) -> Path:
    """Write a configuration document with the overrides applied.

    ``_OMIT`` removes the key, so a missing-key refusal and a malformed-
    value refusal are one helper apart.  A fresh file per call, because
    the variable names the file and the test names the variable.
    """
    document = dict(world.document)
    for key, value in overrides.items():
        if value is _OMIT:
            document.pop(key, None)
        else:
            document[key] = value
    path = Path(world.environment["NULLIUS_EVALUATION_CONFIG"]).parent / (
        f"evaluation-{abs(id(overrides))}.json"
    )
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _environment(
    world: LiveWorld, config_path: Path | None = None, **overrides: str
) -> dict[str, str]:
    """The world's environment, optionally re-pointed and overridden.

    A copy every call: a test that breaks one variable must not break
    the next test's.
    """
    environment = dict(world.environment)
    if config_path is not None:
        environment["NULLIUS_EVALUATION_CONFIG"] = str(config_path)
    for name, value in overrides.items():
        if value is _OMIT:
            environment.pop(name, None)
        else:
            environment[name] = value
    return environment


def _refuses(environment: Mapping[str, str], *needles: str) -> str:
    """Assert the load refuses, opening with the code word, naming the fault.

    Returns the message so a test can pin a clause without re-raising.
    """
    with pytest.raises(EvaluationConfigError) as record:
        load_evaluation_context(environment)
    message = str(record.value)
    assert message.startswith(f"{CODE_WORD}:"), message
    for needle in needles:
        assert needle in message, (needle, message)
    return message


# -- The answer ----------------------------------------------------------------


def test_an_unset_variable_answers_none(world_none: Mapping[str, str]) -> None:
    # The unconfigured state is an answer, not an error: a deployment
    # that runs no live evaluation composes, and the component built on
    # this loader (feature 8) answers None in turn.
    assert "NULLIUS_EVALUATION_CONFIG" not in world_none
    assert load_evaluation_context(world_none) is None


def test_a_blank_variable_answers_none(live: LiveWorld) -> None:
    # The workspace's uniform treatment of an empty environment
    # variable: blank is unset, because a blank path would otherwise
    # look configured while naming nothing.
    assert load_evaluation_context(_environment(live, NULLIUS_EVALUATION_CONFIG=" ")) is None


def test_a_configured_context_answers_the_pipeline_s_own_inputs(
    live: LiveWorld,
) -> None:
    # The one claim the whole feature turns on: the inputs the e2e
    # journey's _run_pipeline assembles by hand — the snapshot handle,
    # the closes, the cost model, the fee schedule — load as they are,
    # stamped with the identity those very bytes resolve to.
    context = load_evaluation_context(live.environment)
    assert isinstance(context, EvaluationContext)

    # The snapshot: the sealed directory, mounted read-only, with the
    # name the seal published.
    assert isinstance(context.snapshot, SnapshotMount)
    assert context.snapshot.name == live.sealed.name
    assert Path(context.snapshot.path) == Path(live.sealed.path)

    # The closes: step 4's own argument, keyed by bar date over the
    # whole sealed span, the venue's string spelling parsed to the
    # finite positive floats the alignment validates.
    assert context.closes == _standard_closes()

    # The cost model: the loaded document's own pair, and the schedule
    # resolved from the same parse — the shared library's rates, with
    # the venue travelling beside them.
    assert isinstance(context.cost_model, CostModelConfig)
    assert context.cost_model.venue == VENUE
    assert context.cost_model.version == VERSION
    assert isinstance(context.cost_schedule, FeeSchedule)
    assert context.cost_schedule.venue == VENUE
    assert context.cost_schedule.taker_bps == TAKER_BPS
    assert context.cost_schedule.maker_bps == MAKER_BPS

    # The provenance triple: the evaluator service's own hash, the
    # manifest's own hash (read through the service, a different door
    # from the mount the loader reads), and the cost-model loader's own
    # fold — three members, three doors, one triple.
    assert (
        context.evaluator_hash
        == EvaluatorService.from_env(live.environment).identity().evaluator_hash
    )
    manifest = live.service.read_manifest(live.sealed.name)
    assert context.snapshot_hash == manifest.snapshot_hash
    assert context.snapshot_hash.startswith(context.snapshot.hash_prefix)
    assert context.cost_model_hash == load_cost_model(live.cost_model_path).hash
    for value in (
        context.evaluator_hash,
        context.snapshot_hash,
        context.cost_model_hash,
    ):
        assert len(value) == 64 and all(c in "0123456789abcdef" for c in value)

    # The run's own facts, exactly as the document and the environment
    # stated them.
    assert context.epoch_id == EPOCH
    assert context.database_url == live.database_url
    assert context.artifact_dir == Path(str(Path(live.document["artifact_dir"])))
    assert context.seed == SEED
    assert context.horizon == HORIZON
    assert context.evaluation_dates == tuple(
        dt.date.fromisoformat(spelling) for spelling in EVALUATION_DAYS
    )
    assert context.sandbox_runtime == "unisolated"


def test_the_context_is_frozen(live: LiveWorld) -> None:
    # Loading provenance in one object only means something if the
    # object cannot be edited between the load and the charge: a
    # context mutated mid-campaign would stamp scores with an identity
    # its own inputs no longer support.
    context = load_evaluation_context(live.environment)
    assert context is not None
    with pytest.raises(dataclasses.FrozenInstanceError):
        context.epoch_id = "epoch-somebody-else"  # type: ignore[misc]


def test_loading_is_deterministic(live: LiveWorld) -> None:
    # §12's determinism starts at the load: the same environment, loaded
    # twice, answers equal contexts — same mount, same closes, same
    # hashes — because every input is a function of the bytes it names.
    first = load_evaluation_context(live.environment)
    second = load_evaluation_context(live.environment)
    assert first is not None and second is not None
    assert first == second


def test_the_cost_model_defaults_to_the_shipped_document(
    live: LiveWorld,
) -> None:
    # NULLIUS_COST_MODEL_PATH is the cost-model member's own variable and
    # keeps that member's own semantics: unset means the shipped §6.2
    # document, not a refusal — the loader re-decides nothing.
    environment = _environment(live, NULLIUS_COST_MODEL_PATH=_OMIT)
    context = load_evaluation_context(environment)
    assert context is not None
    shipped = load_cost_model(None)
    assert context.cost_model == shipped
    assert context.cost_model_hash == shipped.hash


# -- The file ------------------------------------------------------------------


def test_a_missing_file_is_refused(live: LiveWorld) -> None:
    # The variable names a file that does not exist: a run that cannot
    # start, named by the variable that pointed it there.
    _refuses(
        _environment(live, NULLIUS_EVALUATION_CONFIG="/nonexistent/evaluation.json"),
        "NULLIUS_EVALUATION_CONFIG",
        "/nonexistent/evaluation.json",
    )


def test_a_non_json_document_is_refused(live: LiveWorld) -> None:
    # Half a document configures nothing: bytes that are not valid JSON
    # are refused rather than read past.
    path = Path(live.environment["NULLIUS_EVALUATION_CONFIG"])
    path.write_text("{not json", encoding="utf-8")
    _refuses(live.environment, "NULLIUS_EVALUATION_CONFIG", "not valid JSON")


def test_a_non_object_document_is_refused(live: LiveWorld) -> None:
    # The seven keys are an object's keys; a list or a scalar cannot
    # carry them.
    path = Path(live.environment["NULLIUS_EVALUATION_CONFIG"])
    path.write_text(json.dumps(["snapshot_mount"]), encoding="utf-8")
    _refuses(live.environment, "not a JSON object")


@pytest.mark.parametrize("key", CONFIG_KEYS)
def test_a_missing_key_is_refused(live: LiveWorld, key: str) -> None:
    # "There is no default: a missing key is refused" — held per key,
    # because a defaulted key would be worse than a crash: a missing
    # sandbox_runtime silently read as gvisor would assert an isolation
    # nobody configured.
    config = _config_file(live, **{key: _OMIT})
    _refuses(_environment(live, config), f"'{key}' is missing")


def test_the_key_vocabulary_is_closed(live: LiveWorld) -> None:
    # "The file never holds a credential", made structural: a key the
    # loader does not define is refused rather than read past, so a
    # sidecar key reference (the one credential this system's standing
    # constraint forbids the orchestrator to know) cannot ride into a
    # live run under a name the loader silently ignored.
    config = _config_file(live, NULL_SIDECAR_KEY_REF="hex:" + "cd" * 32)
    _refuses(
        _environment(live, config),
        "NULL_SIDECAR_KEY_REF",
        "not a key of the evaluation configuration",
    )


@pytest.mark.parametrize(
    ("epoch_id", "spelling"),
    [
        (5, "5"),
        ("", "''"),
        ("   ", "'   '"),
        (None, "None"),
    ],
)
def test_an_epoch_id_that_is_not_a_non_blank_string_is_refused(
    live: LiveWorld, epoch_id: Any, spelling: str
) -> None:
    # The spec's own named refusal: the epoch every charge is booked
    # against is an opaque non-blank string, and nothing else books.
    config = _config_file(live, epoch_id=epoch_id)
    _refuses(_environment(live, config), "epoch_id", spelling)


@pytest.mark.parametrize(
    ("dates", "reason"),
    [
        ("2026-09-07", "must be a list"),
        ([], "empty"),
        (["09/07/2026"], "not an ISO date"),
        (["20260907"], "not the extended ISO spelling"),
        ([5], "ISO date strings"),
    ],
)
def test_malformed_evaluation_dates_are_refused(
    live: LiveWorld, dates: Any, reason: str
) -> None:
    # The rebalance grid is the days step 2 scores, one vector each; a
    # document that cannot name them names nothing, and a date two
    # tools read two ways is a grid two evaluations could disagree
    # about.
    config = _config_file(live, evaluation_dates=dates)
    _refuses(_environment(live, config), "evaluation_dates", reason)


@pytest.mark.parametrize(
    ("key", "value"),
    [("horizon", "1"), ("horizon", 0), ("horizon", True), ("seed", "5"), ("seed", 1.5), ("seed", True)],
)
def test_malformed_scalars_are_refused(
    live: LiveWorld, key: str, value: Any
) -> None:
    # Shapes a JSON document can get wrong — a string, a float, a
    # boolean — checked where they load rather than where the sandbox
    # first uses them, so a document defect never dresses as a signal
    # defect.  The horizon's *vocabulary* stays the evaluator's own.
    config = _config_file(live, **{key: value})
    _refuses(_environment(live, config), key)


# -- The sandbox gate ---------------------------------------------------------


def test_gvisor_loads_with_runsc_on_the_path(live: LiveWorld) -> None:
    # The isolated runtime loads when the binary is real: a scratch
    # directory holding an executable runsc stands in for a deployment's
    # gVisor install (no host install is assumed), looked up on the PATH
    # the same environment names.  The spelling is compared casefolded
    # and carried canonically, so "gVisor" is one runtime, not two.
    config = _config_file(live, sandbox_runtime=" gVisor ")
    context = load_evaluation_context(
        _environment(live, config, PATH=str(live.runsc_path))
    )
    assert context is not None
    assert context.sandbox_runtime == "gvisor"


def test_gvisor_without_runsc_names_isolation_required(live: LiveWorld) -> None:
    # The spec's own word for what is missing: a configuration that
    # promises gVisor on a PATH that carries no runsc refuses at load,
    # before the mount, the fee claim or a single bar is read — the gate
    # is upstream of everything a run would touch.
    config = _config_file(live, sandbox_runtime="gvisor", acknowledge_unisolated=_OMIT)
    _refuses(
        _environment(live, config),
        "isolation_required",
        "runsc",
        "PATH",
    )


@pytest.mark.parametrize("acknowledgement", [_OMIT, False, "true"])
def test_unisolated_requires_the_acknowledgement(
    live: LiveWorld, acknowledgement: Any
) -> None:
    # The acknowledgement is the operator stating in the artifact that
    # outlives the process that model code runs on the host.  A missing
    # or false one is refused rather than warned — a warning scrolls
    # past, and an unisolated run does not.
    config = _config_file(live, acknowledge_unisolated=acknowledgement)
    _refuses(_environment(live, config), "acknowledge_unisolated")


@pytest.mark.parametrize("runtime", ["firecracker", "docker", None, ""])
def test_a_third_runtime_is_refused(live: LiveWorld, runtime: Any) -> None:
    # Two runtimes and no default: everything else would run model-
    # written code on the host while calling it isolated.
    config = _config_file(live, sandbox_runtime=runtime)
    _refuses(_environment(live, config), "sandbox_runtime")


def test_the_gate_precedes_every_read(live: LiveWorld) -> None:
    # A configuration whose gate refuses must leave the filesystem
    # untouched: no mount re-asserting modes, no fee claimed, no bar
    # read.  The artifact directory proves the negative — a load that
    # wrote anything would have left it behind.
    config = _config_file(live, sandbox_runtime="gvisor", acknowledge_unisolated=_OMIT)
    artifact = Path(live.document["artifact_dir"])
    _refuses(_environment(live, config), "isolation_required")
    assert not artifact.exists()


# -- The environment ----------------------------------------------------------


def test_a_missing_store_is_refused(live: LiveWorld) -> None:
    # The context names the store the node rows and the ledger land in;
    # a deployment that cannot say where learns it at load, not at the
    # first charge.
    _refuses(_environment(live, DATABASE_URL=_OMIT), "DATABASE_URL")


def test_an_unpinned_evaluator_image_is_refused(live: LiveWorld) -> None:
    # The evaluator's own law (feature 70), translated into this
    # module's one error at the seam: the message still names the
    # variable, and the cause stays chained.
    _refuses(
        _environment(live, NULLIUS_EVALUATOR_IMAGE=_OMIT),
        "NULLIUS_EVALUATOR_IMAGE",
    )


def test_a_broken_cost_model_document_is_refused(live: LiveWorld) -> None:
    # The cost-model member's own refusal, carried into the loader's
    # vocabulary: a document the shared library will not price against
    # is a configuration this loader will not serve.
    broken = Path(live.cost_model_path).parent / "broken.yaml"
    broken.write_text("cost_model:\n  venue: only\n", encoding="utf-8")
    _refuses(
        _environment(live, NULLIUS_COST_MODEL_PATH=str(broken)),
        "NULLIUS_COST_MODEL_PATH",
    )


# -- The snapshot and its closes ----------------------------------------------


def test_a_directory_that_is_not_a_sealed_snapshot_is_refused(
    live: LiveWorld,
) -> None:
    # The mount is §4.2's only door onto the market: a path that does
    # not name a sealed snapshot directory refuses here, in the
    # snapshot member's own words carried into this module's error.
    config = _config_file(
        live, snapshot_mount=str(Path(live.document["snapshot_mount"]).parent)
    )
    _refuses(_environment(live, config), "snapshot_mount")


def test_a_snapshot_without_bars_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Labels are measured off the sealed bars; a snapshot that carries
    # none cannot serve an evaluation even though it mounts.  The lake
    # seals cleanly — it holds a valid partition of another stream — so
    # the refusal under test is the loader's missing ``bars``, not the
    # seal's own content checks.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    lake = tmp_path / "lake"
    (lake / "snapshots").mkdir(parents=True)
    partition = lake / "staging" / "trades" / "symbol=SYM00"
    partition.mkdir(parents=True)
    pq.write_table(
        pa.table({"symbol": ["SYM00"], "price": ["1.0"]}),
        partition / "part-0.parquet",
    )
    service = SnapshotService(lake)
    sealed = service.seal(sealed_at=dt.datetime(2026, 11, 1, tzinfo=dt.UTC))
    _refuses(
        _environment_over(str(tmp_path), _standard_document(sealed.path, tmp_path)),
        "snapshot_mount",
        "bars",
    )


def test_a_poisoned_close_is_refused_at_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The aligner's own stated reason, refused where the read happens: a
    # zero close divides every forward return measured off it, and a
    # poison that waited for step 4 would look like an evaluation defect
    # instead of a snapshot one.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    bars = _standard_bars()
    bars["SYM00"][BAR_DAYS[3]] = [0.0]
    _service, sealed = _stage_and_seal(tmp_path / "lake", bars)
    document = dict(_standard_document(sealed.path, tmp_path))
    _refuses(
        _environment_over(str(tmp_path), document),
        "snapshot_mount",
        "SYM00",
        BAR_DAYS[3].isoformat(),
    )


def test_a_duplicate_bar_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # One bar, one close — the aligner's grain, held by the read: a
    # snapshot carrying two candles for one symbol-day has a staging
    # defect a silent merge would hide.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    bars = _standard_bars()
    bars["SYM01"][BAR_DAYS[4]] = [_close(1, 4), _close(1, 4) + 1.0]
    _service, sealed = _stage_and_seal(tmp_path / "lake", bars)
    _refuses(
        _environment_over(str(tmp_path), _standard_document(sealed.path, tmp_path)),
        "twice",
    )


# -- The module's surface -----------------------------------------------------


def test_the_module_s_surface() -> None:
    # Feature 8 re-exports exactly these three names from the package,
    # so this module's public surface must carry them.
    from orchestrator import _context

    for name in ("EvaluationConfigError", "EvaluationContext", "load_evaluation_context"):
        assert name in _context.__all__
    assert issubclass(_context.EvaluationConfigError, Exception)
