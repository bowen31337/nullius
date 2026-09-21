"""Policy documents for the sandbox suite — builders, not fixtures.

Why these live in a uniquely-named module instead of in ``conftest.py``: a
member suite's ``conftest`` is a top-level module called ``conftest``, and so
is every other member's.  The sibling suites that do ``from conftest import
...`` therefore cannot be collected together — pytest imports
``packages/snapshot/tests/conftest.py`` and
``packages/sandbox/tests/conftest.py`` under one module name, the first one to
load wins, and the second member's imports fail with an ``ImportError`` raised
from a file the reader is not looking at.  That is a pre-existing sharp edge in
this workspace, not one this suite invented, but there is no reason for a *new*
suite to widen it.

The split is by kind, which is the honest one: ``conftest.py`` keeps the path
bootstrap, because that is what conftest is for, and the builders below are
ordinary deterministic functions that take their parameters explicitly.  A test
that wants a policy of a different shape calls the function with that shape
rather than re-requesting a fixture, and the import is a plain
``from _documents import ...`` that no other member can shadow.

**Every document here is built fresh rather than shared as a module constant.**
A drift test mutates the document it was handed; a shared constant would make
one test's drift another test's starting point, which is the failure mode
feature 149's sibling suite names for its own helper.  So the builders return
new dicts every call.

The submitted *sources* below are constants, not builders, and that is a
different case rather than an inconsistency: a source is an immutable string
a screen only ever reads, so there is no object for one test's drift to
share with another's — the failure mode the fresh-document rule exists for
cannot happen to a string.  Each is written with its imports on known lines,
because the screen's refusal names the line it found an offender on, and a
test asserting "line 2" against a source whose import drifted to line 3
would be asserting a coincidence.
"""

from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any

import polars as pl
import pyarrow as pa
from contract import MarketWindow
from contract.signal import validate_signal_return
from sandbox import (
    ENV_MKL,
    ENV_OMP,
    IMPORTS_POLICY_KIND,
    PINNING_POLICY_KIND,
    POLICY_KIND,
    POOL_FLOOR_VARIABLE,
    SINGLE_THREADED,
    SandboxInvocation,
    encode_scores,
)

#: The two Z1 boxes §3's component map draws — the same membership feature
#: 148's committed credential grant and feature 149's committed egress policy
#: carry, so a test naming them is naming one deployment's boxes rather than
#: inventing a third.
SIGNAL_SANDBOX: str = "signal-sandbox"
POLICY_RUNTIME: str = "policy-runtime"

#: §5.2's isolation row verbatim: the mechanism and the runtime a compliant
#: component declares.  Spelled here as data so a drift test can vary *one* of
#: them and leave the other compliant — which is how "the pair is checked, not
#: just the mechanism" is provable rather than asserted.
GVISOR: dict[str, str] = {"mechanism": "gvisor", "runtime": "runsc"}

#: The near-miss runtimes a drifted deployment reaches for: the OCI runtime
#: Docker uses by default, so a box that "is a container" and believes it is
#: sandboxed carries it; and a micro-VM, which §5.2's table names as the
#: *alternative* mechanism and which this deployment deliberately did not
#: choose (§18 picks gVisor runsc).  Both are refused.
DEFAULT_OCI_RUNTIME: str = "runc"
MICROVM_MECHANISM: str = "firecracker"

#: A component the committed policy does not list — the run whose box the
#: policy cannot speak about.
UNLISTED_COMPONENT: str = "unlisted-runtime"


def isolation_block(
    *, mechanism: str = GVISOR["mechanism"], runtime: str = GVISOR["runtime"]
) -> dict[str, str]:
    """One component's ``isolation`` block, compliant unless told otherwise."""
    return {"mechanism": mechanism, "runtime": runtime}


def isolation_document(
    *components: tuple[str, dict[str, str]],
) -> dict[str, Any]:
    """A well-formed policy document from ``(name, isolation)`` pairs.

    The caller passes the pairs explicitly — rather than this builder defaulting
    to the committed membership — so a test that means "a policy covering only
    the signal sandbox" says exactly that, and a test that means "the committed
    membership" asks :func:`committed_document` instead.  A default here would
    make the two indistinguishable at the call site.
    """
    return {
        "policy": POLICY_KIND,
        "components": [
            {"name": name, "isolation": dict(block)} for name, block in components
        ],
    }


def committed_document() -> dict[str, Any]:
    """The committed artifact's shape: both Z1 boxes, each under gVisor.

    Built fresh so a test can drift it without touching its siblings' copies,
    and deliberately shaped after the file on disk rather than read *from* it —
    the artifact's own tests read the file (:mod:`test_artifact`), so a builder
    that read it too would make a drift in the file invisible to every test
    that meant to build a document instead.
    """
    return isolation_document(
        (SIGNAL_SANDBOX, isolation_block()),
        (POLICY_RUNTIME, isolation_block()),
    )


def document_with_runtime(
    runtime: str, *, component: str = SIGNAL_SANDBOX
) -> dict[str, Any]:
    """A drift document: one component on a non-gVisor runtime.

    The whole document is otherwise well-formed and every other component is
    compliant, because the law under test is not "bad documents are refused"
    but "a document that would run untrusted code without gVisor is refused
    *as* one" — the refusal must fire on drift that would parse, apply and
    read as policy if the law were not there.
    """
    document = committed_document()
    for block in document["components"]:
        if block["name"] == component:
            block["isolation"] = isolation_block(runtime=runtime)
    return document


def document_with_mechanism(
    mechanism: str, *, component: str = SIGNAL_SANDBOX
) -> dict[str, Any]:
    """A drift document: one component on a non-gVisor mechanism.

    The runtime stays compliant while the mechanism drifts, so a policy that
    checked the runtime alone would admit this document — which is the
    half-check the law exists to close.
    """
    document = committed_document()
    for block in document["components"]:
        if block["name"] == component:
            block["isolation"] = isolation_block(mechanism=mechanism)
    return document


def document_without_isolation(*, component: str = SIGNAL_SANDBOX) -> dict[str, Any]:
    """A drift document: one component's isolation block is absent.

    ``absent`` and ``held to gVisor by law`` are different promises, and only
    the second is feature 157's — so silence must not read as the strongest
    promise the document makes.
    """
    document = committed_document()
    for block in document["components"]:
        if block["name"] == component:
            del block["isolation"]
    return document


# ---------------------------------------------------------------------------
# Feature 167 — the import allowlist, and the modules submitted against it.
# ---------------------------------------------------------------------------

#: §5.2's payload stack, the terms the committed ceiling admits that a
#: submitted signal plausibly reaches for: §5.1's contract is polars-native,
#: the numeric layer sits beneath it, and the window arrives as Arrow IPC.
POLARS: str = "polars"
NUMPY: str = "numpy"
PYARROW: str = "pyarrow"

#: The module §12's determinism row names first — the one import the
#: committed ceiling refuses by *listing nothing for it*, because every use
#: of it is a wall-clock read and there is no sanctioned spelling to admit.
TIME_MODULE: str = "time"

#: A module no ceiling in this deployment names — the plain offender, one a
#: drifted or hostile submission reaches for and a reader of the refusal
#: recognises on sight.
OS_MODULE: str = "os"

#: The committed ceiling's terms, spelled as data so a drift test can vary
#: *one* of them (drop a term, add a hole) and leave the rest the artifact's
#: — the same role :data:`GVISOR` plays for the isolation document, and the
#: same order the file on disk carries so a test comparing compiled order to
#: document order reads the same list.
COMMITTED_ALLOWLIST_TERMS: tuple[str, ...] = (
    "math",
    "decimal",
    "fractions",
    "statistics",
    "itertools",
    "functools",
    "datetime",
    "random",
    "typing",
    "collections",
    "dataclasses",
    "__future__",
    POLARS,
    NUMPY,
    PYARROW,
)


def allowlist_document(*terms: str) -> dict[str, Any]:
    """A well-formed allowlist document from the terms the caller names.

    The caller passes the terms explicitly — rather than this builder
    defaulting to the committed ceiling — so a test that means "a ceiling
    admitting only math" says exactly that, and a test that means "the
    committed ceiling" asks :func:`committed_allowlist_document` instead.
    A default here would make the two indistinguishable at the call site,
    the same reason :func:`isolation_document` takes its pairs explicitly.
    """
    return {"policy": IMPORTS_POLICY_KIND, "allow": list(terms)}


def committed_allowlist_document() -> dict[str, Any]:
    """The committed artifact's shape: the deterministic working set, the
    structure modules, the compiler directive and the payload stack.

    Built fresh and shaped after the file on disk rather than read *from*
    it, for the reason :func:`committed_document` gives: the artifact's own
    tests read the file (:mod:`test_imports_artifact`), so a builder that
    read it too would make a drift in the file invisible to every test that
    meant to build a ceiling instead.
    """
    return allowlist_document(*COMMITTED_ALLOWLIST_TERMS)


#: A submission whose every import is inside the committed ceiling — in the
#: shapes a real module writes them: the compiler directive, a plain
#: import, a from-import binding a name, an aliased import, and a
#: from-import binding a subpackage (``numpy.linalg``, judged as the
#: subpackage it lands on).  Five shapes, one ceiling, all covered.
SOURCE_WITHIN: str = (
    "from __future__ import annotations\n"
    "import math\n"
    "from decimal import Decimal\n"
    "import polars as pl\n"
    "from numpy import linalg\n"
)


#: A submission reaching for the world the box refuses: ``os`` on line 1 and
#: ``socket`` on line 3, so a refusal naming *both* with *both* lines is a
#: test of the collective refusal rather than of whichever offender a
#: screen happened to report first.
SOURCE_WITH_OS_AND_SOCKET: str = (
    "import os\n" "import math\n" "import socket\n"
)

#: The wall-clock module §12 names — absent from the committed ceiling by
#: construction, so this submission is refused *by the ceiling*, which is a
#: different fact from being refused by a hole.
SOURCE_WITH_TIME: str = "import time\n"

#: A relative import: a submitted module is one module, not a package with
#: siblings, and the box holds no package for ``.`` to resolve against.
SOURCE_RELATIVE: str = "from . import sibling\n"

#: Source that does not parse, with the break on line 2 so the refusal can
#: be expected to name it.
SOURCE_UNPARSABLE: str = "import math\ndef broken(:\n"

#: A submission importing the parent of a term the ceiling names — the
#: half-check a prefix rule must close: an entry admitting ``numpy.linalg``
#: does not admit ``numpy``, because importing the parent executes it.
SOURCE_IMPORTING_PARENT: str = "import numpy\n"


# ---------------------------------------------------------------------------
# Feature 166 — the payload channel: a window, and the scores it returns.
#
# These are *builders*, not constants, and they are the one place in this
# module where that matters for a reason beyond drift: the objects below are
# mutable Arrow tables and mutable series, and a shared one would let a test
# that wrote into a frame (or dispatched a channel) change what the next test
# read.  The same fresh-object rule :func:`isolation_document` states for its
# dicts, applied to the payload stack.
# ---------------------------------------------------------------------------

#: The decision time the windows below are sliced at.  Pinned rather than
#: ``now()`` for the reason §12 gives for every other instant in this
#: repository: a materialized window is a point-in-time fact, and a test
#: that read the wall clock would assert against a moving target.
WINDOW_DECISION_TIME: datetime.datetime = datetime.datetime(
    2024, 1, 1, tzinfo=datetime.UTC
)

#: The symbols a window in these tests holds — three, so a positional score
#: vector has an order to be checked against and a length that a
#: wrong-length return can plausibly disagree with.
WINDOW_UNIVERSE: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT")

#: The one frame a window here materializes.  §5.2's call site sends a
#: *materialized* window; a window with no frames is refused by feature 14's
#: serializer, which is a case its own suite covers and this one re-checks
#: through the channel's translation of the refusal.
WINDOW_FRAME_NAME: str = "bars:1d"

#: Scores aligned to :data:`WINDOW_UNIVERSE`, in a deliberately mixed sign
#: and non-integral shape: a vector whose values were ``[1, 2, 3]`` could be
#: read back correctly by an integer-tolerant reader that should have been
#: refused, and one whose signs are all positive could hide a sign-flip.
WINDOW_SCORES: tuple[float, ...] = (0.75, -1.25, 2.5)


def window_frames(
    *,
    rows: int = 3,
    frame_names: tuple[str, ...] = (WINDOW_FRAME_NAME,),
) -> dict[str, Any]:
    """A fresh frame mapping, one column of ``rows`` integers per frame.

    Rebuilt per call because an Arrow table can be rebound into another
    window and a test that drifted one would otherwise drift its sibling's.
    Each frame is its own table, so a multi-frame window here carries
    genuinely distinct payloads rather than one table bound under two names —
    which is what makes a mis-indexed segment read *wrong* instead of
    accidentally right.
    """
    return {
        name: pa.table({"close": list(range(1, rows + 1))}) for name in frame_names
    }


def materialized_window(
    *,
    universe: tuple[str, ...] = WINDOW_UNIVERSE,
    t: datetime.datetime = WINDOW_DECISION_TIME,
    frame_names: tuple[str, ...] = (WINDOW_FRAME_NAME,),
    rows: int = 3,
) -> MarketWindow:
    """A materialized window over the given universe, frames real Arrow.

    A real :class:`contract.window.MarketWindow` over a real Arrow table — not
    a stand-in — because feature 166's inbound leg is *feature 14's payload*,
    and a hand-written substitute would test this module against bytes the
    contract never produces.  The same discipline ``evaluator``'s sandbox
    suite states for its own windows.

    ``rows`` is settable because an empty universe and a frame of bars are
    independent: a window can hold no symbols and no rows (the empty case), and
    a test that wants one needs to say so rather than rely on a default that
    happens to be true for the other.
    """
    return MarketWindow(
        t, universe, frames=window_frames(rows=rows, frame_names=frame_names)
    )


def unmaterialized_window(
    *,
    universe: tuple[str, ...] = WINDOW_UNIVERSE,
    t: datetime.datetime = WINDOW_DECISION_TIME,
) -> MarketWindow:
    """A window with no frames — what a host that never sliced has in hand.

    Feature 14 refuses to serialize one, because the box has no mounts to read
    a frame from; through the channel that refusal must arrive as this
    member's own error rather than the contract's.
    """
    return MarketWindow(t, universe)


def score_series(values: object = WINDOW_SCORES, *, name: str = "scores"):
    """A fresh :class:`polars.Series` of the given values, Float64.

    The type feature 11 declares a signal returns, so the encode path is
    exercised with what a real producer hands back rather than with a list
    that happened to work.
    """
    return pl.Series(name, list(values), dtype=pl.Float64)


def contract_validate(series: object, universe: tuple[str, ...]) -> list[Any]:
    """Feature 11's own verdict on a return, for the same universe.

    The channel judges a score vector on the wire; the contract judges the
    same vector inside the box.  A test that wants to compare the two
    verdicts has to ask the contract directly, and this is that question —
    named here rather than imported at each call site so the seam being
    checked is visible in the test that checks it.
    """
    return validate_signal_return(series, universe)


def score_payload(
    values: object = WINDOW_SCORES,
    *,
    universe: tuple[str, ...] = WINDOW_UNIVERSE,
    decision_time: str | None = None,
    contract_version: str | None = None,
) -> bytes:
    """A score vector encoded for ``universe`` — a return leg, ready to send.

    Built through the module's own encoder rather than by hand, so a test that
    wants to *read* a payload, or to violate it and watch the reader refuse,
    starts from bytes this implementation actually writes.
    """
    return encode_scores(
        score_series(values),
        universe=universe,
        decision_time=decision_time,
        contract_version=contract_version,
    )


# ---------------------------------------------------------------------------
# Feature 165 — the node seed, the invocations that carry it, the records it
# lands on.
#
# These are *builders* rather than constants for the reason the section above
# gives and one more of its own: the record builders below return objects a
# test deliberately mutates (a drift test writes a second seed onto a record),
# so a shared one would make one test's drift another test's starting point —
# the failure mode :func:`isolation_document` states for its own dicts, applied
# to the seed's two carriers.  The *seeds* are constants, because the value a
# signature is checked against is data, and a builder that minted a fresh one
# per call would make "this run carried seed 7" unwritable.
# ---------------------------------------------------------------------------

#: The node the invocations below belong to — a UUID-shaped string, because
#: that is what §9.1's ``node.id`` holds and what :func:`sandbox.mint_node_seed`
#: is keyed on.  Spelled rather than generated so a test asserting a minted seed
#: has one value to assert.
SEED_NODE_ID: str = "5f3c1a1e-0d1f-4f6a-9a62-7c2b5d4e8a01"

#: A second node, so "two nodes get two seeds" has two identities to compare —
#: the property :func:`nulloracle.selection.perm_seed_for` states for its own
#: derivation, and the reason a seed is minted per node rather than per run.
OTHER_SEED_NODE_ID: str = "9b1d6c44-2e77-4a0b-8f3d-1c5a7e9b2d10"

#: The seed these tests use when they mean "a good one" — small, positive and
#: unmistakable in a repr, so a failure message says which value went where.
NODE_SEED: int = 7

#: A second good seed, for the re-seed tests: distinct from :data:`NODE_SEED`
#: so "a different seed" is a different number rather than a coincidence.
OTHER_NODE_SEED: int = 424242

#: §5.2's component the run belongs to, the same box feature 157's committed
#: policy lists — named here so the invocation builders default to a real
#: member of the deployment rather than to an invented third box.
SEED_COMPONENT: str = SIGNAL_SANDBOX


def invocation(
    *,
    node_id: str = SEED_NODE_ID,
    seed: Any = NODE_SEED,
    component: str = SEED_COMPONENT,
    env: Mapping[str, str] | None = None,
) -> SandboxInvocation:
    """A fresh invocation for ``node_id``, carrying ``seed`` by default.

    ``seed`` is typed ``Any`` and defaults to a *good* value rather than to
    ``None``: a test that means "this invocation has no seed" says so by
    passing ``None``, and one that means "this one is fine" does not have to
    restate the seed.  A default of ``None`` would make every builder call in
    this suite read as a seedless run, which is the state the law exists to
    refuse.
    """
    return SandboxInvocation(
        node_id=node_id, seed=seed, component=component, env=env
    )


def seedless_invocation(
    *,
    node_id: str = SEED_NODE_ID,
    component: str = SEED_COMPONENT,
    env: Mapping[str, str] | None = None,
) -> SandboxInvocation:
    """An invocation whose seed is absent — the refusal's own subject.

    Its own builder rather than ``invocation(seed=None)`` so the two tests that
    disagree about *which* absence is the worst one read as themselves: the
    keyword omitted entirely is the same state as ``None`` to this law, and the
    suite checks that they are the same state rather than assuming it.

    Everything *else* about the invocation is ordinary: a seedless run is a run
    that reached the launcher, which is the whole reason the law has to refuse
    it rather than a caller simply not building one.
    """
    return SandboxInvocation(node_id=node_id, seed=None, component=component, env=env)


def node_record(
    *,
    node_id: str = SEED_NODE_ID,
    seed: Any = NODE_SEED,
) -> dict[str, Any]:
    """A fresh node record — a mutable mapping, the shape §9.1's row arrives in.

    A dict rather than a dataclass because that is what a relational driver
    hands back and because a test that drifts one needs a record it can write
    into: §9.1's ``node`` row is the record this feature's second half persists
    the seed on.
    """
    record: dict[str, Any] = {"node_id": node_id}
    if seed is not None:
        record["seed"] = seed
    return record


class SeedRecordRow:
    """A node record as an *object* rather than a mapping — the other shape.

    Deliberately attribute-carrying rather than a dataclass: the suite's point
    is that the law reads both shapes, and a dataclass with a ``seed`` field
    would be the members' own record type rather than a third thing that
    happens to look like it.  ``node_id`` defaults to the module's own node so
    a test that only wants the object spelling writes one line.
    """

    __slots__ = ("node_id", "seed")

    def __init__(self, node_id: str = SEED_NODE_ID, seed: Any = NODE_SEED) -> None:
        self.node_id = node_id
        self.seed = seed


# ---------------------------------------------------------------------------
# Feature 164 — the thread-pinning environment.
#
# The builders below are the *environment* half of §5.2's call site, and they
# are spelled from the two cap names as *data* rather than by importing the
# member's own constants: the law's tests pin that the spelling is
# ``"OMP_NUM_THREADS"`` and the pin is ``"1"``, and a suite that imported them
# would follow a rename instead of catching one.  The same discipline feature
# 165's tests apply to ``NULLIUS_SIGNAL_SEED``.  The two constants imported
# above (``ENV_OMP``, ``ENV_MKL``, ``SINGLE_THREADED``, ``POOL_FLOOR_VARIABLE``)
# are used only by the builders that build a *policy document*, where the
# artifact's own shape is what is being reproduced.
# ---------------------------------------------------------------------------

#: §5.2's call site, verbatim: the two caps §12 names, each at the pin.  A
#: builder rather than a constant (below) because a drift test mutates the
#: environment it was handed — the suite's fresh-object rule.
OMP: str = "OMP_NUM_THREADS"
MKL: str = "MKL_NUM_THREADS"
PIN: str = "1"

#: A third variable of the kind §5.2's call site also carries — ``PYTHONHASHSEED``
#: is feature 138's law, not this one's, and it rides along here so the tests can
#: prove the pinning law neither requires nor disturbs variables outside its
#: table: the environment it hands back must carry the subject's other keys
#: untouched.
BYSTANDER: str = "PYTHONHASHSEED"

#: The layer each cap governs, spelled here so a test asserting that a refusal
#: *names the library left threaded* has the words to assert against.
OMP_LAYER: str = "the OpenMP-parallel BLAS kernels"
MKL_LAYER: str = "the Intel MKL threading layer"


def thread_pinned_env(**overrides: Any) -> dict[str, Any]:
    """A fresh environment carrying §5.2's pins — the passing case.

    ``overrides`` replace individual declarations, so a test that means "the MKL
    cap is threaded" writes ``thread_pinned_env(**{MKL: "4"})`` and one that
    means "the OMP cap is missing" writes ``thread_pinned_env(**{OMP: None})`` —
    the same "state the one thing you varied" shape
    :func:`document_with_runtime` gives the isolation policy.  ``None`` *removes*
    the key rather than writing it, because "absent" and "declared as None" are
    different states of an environment and the law distinguishes them.
    """
    env: dict[str, Any] = {OMP: PIN, MKL: PIN, BYSTANDER: "0"}
    for name, value in overrides.items():
        if value is None:
            env.pop(name, None)
        else:
            env[name] = value
    return env


def unpinned_env() -> dict[str, Any]:
    """A fresh environment missing both caps — feature 164's own subject.

    Its own builder rather than ``thread_pinned_env(**{OMP: None, MKL: None})``
    so the refusal tests read as themselves: this is §5.2's call site with the
    ``env=`` clause left out of the determinism half, which is the invocation
    the feature exists to refuse.  The bystander is kept, so the refusal is
    about the two names §12 lists and not about an empty mapping.
    """
    return {BYSTANDER: "0"}


def pinning_document(
    *,
    caps: list[dict[str, Any]] | None = None,
    floors: list[str] | None = None,
    policy: str = PINNING_POLICY_KIND,
) -> dict[str, Any]:
    """A well-formed pinning document from the blocks the caller names.

    The caller passes the caps explicitly — rather than this builder defaulting
    to the committed pair — so a test that means "a policy pinning only OMP"
    says exactly that, and a test that means "the committed policy" asks
    :func:`committed_pinning_document` instead.  A default here would make the
    two indistinguishable at the call site, the same reason
    :func:`isolation_document` and :func:`allowlist_document` take their
    subjects explicitly.
    """
    if caps is None:
        caps = [
            {"name": ENV_OMP, "value": SINGLE_THREADED, "layer": OMP_LAYER},
            {"name": ENV_MKL, "value": SINGLE_THREADED, "layer": MKL_LAYER},
        ]
    if floors is None:
        floors = [POOL_FLOOR_VARIABLE]
    return {"policy": policy, "caps": caps, "pool_floors": floors}


def committed_pinning_document() -> dict[str, Any]:
    """The committed artifact's shape: §12's two caps at the pin, one floor.

    Built fresh and shaped after the file on disk rather than read *from* it,
    for the reason :func:`committed_document` gives: the artifact's own tests
    read the file (:mod:`test_thread_artifact`), so a builder that read it too
    would make a drift in the file invisible to every test that meant to build a
    policy instead.
    """
    return pinning_document()


# ---------------------------------------------------------------------------
# Feature 163 — the wall-clock budget (session §5.2's ``limits=Limits(wall_s=30,
# …)``) and the two durations a run is judged by.  A builder rather than a
# constant below, for the suite's fresh-object rule; the budget itself is a
# *number*, though, and a number is immutable — so the scalar is a constant and
# only the *documents* carrying it are builders.  The same distinction the
# module docstring draws for the submitted sources.
# ---------------------------------------------------------------------------

#: §5.2's budget, spelled as *data* rather than imported from
#: :data:`sandbox.timeout.DEFAULT_WALL_S`: a test that read the constant would
#: follow a rename of the number instead of catching one, and the feature's own
#: sentence ("its 30 second wall clock budget") is what this suite is holding
#: the law to.  The law's compile pins the constant to this value in
#: :mod:`test_timeout_law`; here it is the number the *documents* are built with.
WALL_S: float = 30.0

#: An elapsed time a watchdog would report for a run that outran §5.2's budget —
#: comfortably past it rather than a hair, so a test that means "killed" is not
#: secretly a boundary test, and the overrun the kill sentence names is a value
#: with room in it (``OVERRUN_S`` past the budget).
OVERRUN_S: float = 47.5

#: An elapsed time comfortably *inside* the budget — the run that finished and
#: was never killed.  §6.1 step 2 dispatches thousands of these for every one
#: that hangs, so the pass-through is the common case rather than a corner.
WITHIN_S: float = 3.25

#: §5.2's budget itself, as the elapsed time — the boundary case, and its own
#: constant because the reading of it is the one judgement in this law that
#: could reasonably have gone the other way.  *Exceeded* is strict: a run that
#: took exactly its budget did not exceed it, so this elapsed time is **not** a
#: kill, and a test asserting that says so by name.
AT_BUDGET_S: float = WALL_S

#: The two durations a *malformed* elapsed time is drawn from: the shape §9.1's
#: column, a JSON document or an environment variable would hand one over as
#: (text), and a value that looks like a number to a reader and is not one to a
#: comparison (a flag — ``True`` is an ``int`` in Python).  Both are refused by
#: name rather than coerced, which is the property the alias tests pin.
TEXT_DURATION: str = "47.5s"
FLAG_DURATION: bool = True


def timeout_run(
    *,
    elapsed_s: Any = OVERRUN_S,
    budget_s: Any = WALL_S,
    node_id: str = "",
    component: str = "",
) -> Any:
    """A fresh run as the wall-clock law sees it — over budget unless told.

    Defaults to the *killed* case because that is the feature's subject: a test
    that means "this one finished in time" passes ``elapsed_s=WITHIN_S`` and
    says so, rather than the other way round, where the interesting case would
    be the one a reader had to notice at the call site.  ``budget_s`` is the run's
    own record of what it was dispatched under — distinct from the *policy's*
    compiled budget, which is what the gate actually compares against, so a test
    can put the two in disagreement on purpose.

    Imported from :mod:`sandbox.timeout` here rather than re-spelled as a dict,
    because a run is not a *document*: the law reads it as an object with two
    durations on it, and a builder handing over a bare mapping would be testing
    a shape the law does not claim to accept.  The law's tolerance for
    duck-typed subjects is exercised with an explicit stand-in in the law suite.
    """
    from sandbox.timeout import TimeoutRun

    return TimeoutRun(
        elapsed_s=elapsed_s,
        budget_s=budget_s,
        node_id=node_id,
        component=component,
    )


def timeout_document(
    *,
    wall_s: Any = WALL_S,
    policy: str = "sandbox-timeout",
    include_wall: bool = True,
) -> dict[str, Any]:
    """A well-formed timeout document, drifted only where the caller says.

    ``policy`` and ``wall_s`` are parameters rather than this builder reaching
    for the committed kinds, for the reason :func:`pinning_document` gives: a
    test that means "a document that does not declare itself" says exactly that,
    and a test that means "the committed policy" asks
    :func:`committed_timeout_document` instead.  ``include_wall=False`` builds
    the *silent* document — the one that omits the budget entirely — which is a
    different refusal from a budget of the wrong value, and the law says so.

    The marker is written as the literal ``"sandbox-timeout"`` here rather than
    read from :data:`sandbox.timeout.TIMEOUT_POLICY_KIND`, deliberately: a
    document is an *input* to the compile, and a builder that had to import the
    module under test to be constructible would couple every drift test's
    premise to the thing being tested — the discipline the submitted sources in
    this module already follow.
    """
    document: dict[str, Any] = {"policy": policy}
    if include_wall:
        document["wall_s"] = wall_s
    return document


def committed_timeout_document() -> dict[str, Any]:
    """The committed artifact's shape: §5.2's budget, and the marker.

    Shaped after the file on disk rather than read *from* it, for the reason
    :func:`committed_pinning_document` gives: the artifact's own tests read the
    file (:mod:`test_timeout_artifact`), so a builder that read it too would
    make a drift in the file invisible to every test that meant to build a
    document instead.
    """
    return timeout_document()


def node_fail_class_record(
    *,
    node_id: str = SEED_NODE_ID,
    fail_class: Any = None,
    field: str = "fail_class",
) -> dict[str, Any]:
    """A fresh §9.1 ``node`` row, with an optional terminal class already on it.

    The write half's subject: :func:`sandbox.timeout.timed_out_record` persists
    the timeout class onto a record like this one, and the tests here need the
    three starting states distinct — *no class yet* (the unevaluated node),
    *the same class* (a retried kill, which is idempotent) and *a different one*
    (a node that already died some other way, which is refused rather than
    overwritten).  ``field`` lets a test put the class under the ledger's
    ``outcome`` spelling instead of §9.1's ``fail_class``, because the two rows
    are two shapes of the same fact and the law reads both.

    A dict rather than a dataclass because that is what §9.1's row arrives as
    from a relational driver — the mapping shape is the one that matters at this
    seam, and the attribute shape is exercised with an explicit stand-in in the
    law suite rather than smuggled in here.
    """
    record: dict[str, Any] = {"node_id": node_id}
    if fail_class is not None:
        record[field] = fail_class
    return record
