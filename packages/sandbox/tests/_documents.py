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
    "import pyarrow as pa\n"
)


#: A submission reaching for the world the box refuses: ``os`` on line 1 and
#: ``socket`` on line 3, so a refusal naming *both* with *both* lines is a
#: test of the collective refusal rather than of whichever offender a
#: screen happened to report first.
SOURCE_WITH_OS_AND_SOCKET: str = "import os\nimport math\nimport socket\n"

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
    return {name: pa.table({"close": list(range(1, rows + 1))}) for name in frame_names}


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
    return SandboxInvocation(node_id=node_id, seed=seed, component=component, env=env)


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


# ---------------------------------------------------------------------------
# Feature 168 — the fail-class vocabulary and its translation table.
#
# The constants below are spelled as *data* rather than imported from
# :mod:`sandbox.failclass`, for the reason the wall-clock section above gives
# about ``WALL_S``: a suite that read the law's own constants would follow a
# rename instead of catching one, and it is §9.1's column comment — verbatim —
# that the law is being held to.  The law's own spellings are pinned against
# these in :mod:`test_failclass_law`.
#
# The classes the *box* reports are equally spelled here rather than read from
# :class:`evaluator.SandboxResult`: the sandbox member imports no other workspace
# member (one provenance), so the suite that makes the restatement safe is this
# one, and it asserts the two agree by importing the evaluator in a single test.
# ---------------------------------------------------------------------------

#: §9.1's column comment, verbatim: ``fail_class TEXT -- ok | timeout | error |
#: tripwire_fail``.  Written out so a reordering or a dropped class on the
#: sandbox side fails here rather than being followed.
NODE_CLASSES: tuple[str, ...] = ("ok", "timeout", "error", "tripwire_fail")

#: The six classes the runner records, from :class:`evaluator.SandboxResult`'s
#: own docstring — its four terminal states, spelled out.  ``timeout`` is one of
#: §9.1's four already; the other five are §8's "failed any other way".
RUNNER_CLASSES: tuple[str, ...] = (
    "timeout",
    "oom",
    "crash",
    "violation",
    "payload",
    "empty",
)

#: Feature 161's seccomp verdict — app_spec.xml's own spelling, with the
#: underscore, and deliberately **not** one of §9.1's four: it is a genuine
#: seccomp verdict rather than a terminal class of the column, which is why
#: feature 163 refuses to write over it and why translating it is feature 168's
#: job.
ESCAPE_CLASS: str = "sandbox_escape"

#: A class no deployment's box reports, for the *unknown* refusal.  Chosen to be
#: a plausible misspelling of a real one — the drift this law exists to catch —
#: rather than an obviously invented word: a law that folded ``"TimeOut"`` into
#: ``error`` would read every wall-clock kill as a generic crash, and the test
#: that says so is this constant's only job.
UNKNOWN_CLASS: str = "TimeOut"

#: The two spellings a *class* may arrive under that are not §9.1's column name
#: — §8's ledger ``outcome`` and the store rows' ``terminal_class``.  The law
#: reads all three, and a test that only ever wrote ``fail_class`` would not
#: notice a reader that had dropped the other two.
LEDGER_FIELD: str = "outcome"
TERMINAL_FIELD: str = "terminal_class"


def runner_result(
    *,
    fail_class: Any = "crash",
    problems: list[Any] | None = None,
    seed: Any = None,
) -> Any:
    """A fresh stand-in for the runner's own result — the object the box hands back.

    Deliberately a plain class carrying the fields
    :class:`evaluator.SandboxResult` declares, rather than that type itself: the
    sandbox member imports no other workspace member, so a suite here cannot
    build one without reaching across the seam the member refuses to cross.  The
    law reads subjects duck-typed — the same tolerance
    :func:`sandbox.timeout.kill_timeout` extends to an ``elapsed_s`` on anything
    — and what matters to this feature is the field *names* it reads, not the
    class name.

    **It carries no node identity, because the real result does not either.**
    :class:`evaluator.SandboxResult` is the *outcome of one signal execution* —
    ``scores``, ``problems``, ``fail_class``, ``detail``, ``seed``,
    ``contract_version`` — and names no node: the caller that dispatched the run
    is the one that knows which node it belonged to.  So a test that means "this
    class is recorded against node X" passes ``node_id=`` to
    :func:`sandbox.failclass.classify_run` rather than smuggling an identity into
    the result, which is exactly the courtesy that verb's own ``node_id``
    parameter exists for.

    Defaults to ``fail_class="crash"``, the *translated* case, because that is
    the feature's headline: a class the box's own vocabulary has and §9.1's
    column does not.  A test that means "this run was scored" passes
    ``fail_class=None`` with the default empty ``problems``; one that means "the
    contract refused the return" passes a non-empty ``problems``.
    """
    result = _RunnerResult()
    result.fail_class = fail_class
    result.problems = [] if problems is None else list(problems)
    result.seed = seed
    return result


class _RunnerResult:
    """The shape of the box's own result — its six fields, no behaviour.

    Field for field what :class:`evaluator.SandboxResult` declares, so the
    cross-member test that pins the two agree has something faithful to compare
    against.  Not a dataclass: the suite's point is that the law reads
    *attributes*, and a dataclass would make this look like the members' own
    record type rather than a third thing that happens to carry the same names.
    """

    __slots__ = (
        "contract_version",
        "detail",
        "fail_class",
        "problems",
        "scores",
        "seed",
    )

    def __init__(self) -> None:
        self.scores: Any = None
        self.problems: list[Any] = []
        self.fail_class: Any = None
        self.detail: str = ""
        self.seed: Any = None
        self.contract_version: str = ""


def tripwire_outcome(
    *,
    rejected: bool = True,
    node_id: str = SEED_NODE_ID,
) -> dict[str, Any]:
    """A fresh tripwire verdict's shape — step 10's answer, as the law reads it.

    The tripwires member's own verdict carries ``outcome`` alongside a dozen
    other fields; this is the half this feature has a claim about, spelled as a
    mapping so the *reader* is what is under test rather than a second copy of
    another member's record type.  ``rejected=True`` gives the verdict that
    failed — ``tripwire_fail`` — because that is the class §9.1's column has a
    word for and the one the pipeline quarantines a subtree on.
    """
    return {
        "node_id": node_id,
        "outcome": "tripwire_fail" if rejected else "ok",
        "rejected": rejected,
    }


# ---------------------------------------------------------------------------
# Feature 162 — the cgroup limits (app_spec.xml §5.2's resource row)
#
# The fifth artifact-backed feature in this category, and the one whose subject
# is a run's *measured consumption* — §5.2's ``limits=Limits(wall_s=30,
# cpu_s=30, mem_mb=2048, network=False, filesystem=False, pids=32)`` clause, of
# which feature 163 owns ``wall_s`` and this law owns the other three.  §5.2's
# control table row is ``Resources | cgroup v2: cpu.max, memory.max, pids.max``.
#
# The three numbers are spelled here as *data* rather than imported from
# :data:`sandbox.budget.DEFAULT_CPU_S` &c., for the reason :data:`WALL_S` gives
# one law over: a test that read the constants would follow a rename of the
# limits instead of catching one, and the feature's own sentence ("the cgroup
# limits for cpu, memory of 2048 MB or a process count of 32") is what this
# suite holds the law to.
# ---------------------------------------------------------------------------

#: §5.2's cpu budget, in seconds — the same number feature 163 reads as its wall
#: clock, and deliberately the same *value*: §5.2's call site passes ``cpu_s=30``
#: beside ``wall_s=30``, and a deployment where they drifted apart would be one
#: whose cpu budget the watchdog could never reach.
CPU_S: float = 30.0

#: The feature's own memory limit: "memory of 2048 MB".  Two gigabytes, spelled
#: as the sentence spells it, and *not* the 4096 an ``RLIMIT_AS`` fallback needs
#: — see :data:`RUNNER_MEM_MB`.
MEM_MB: int = 2048

#: The feature's own process-count limit: "a process count of 32".  §12's
#: eight-task executor bound is a different plane and a coincidentally different
#: number; a test that meant *this* limit says ``PIDS``.
PIDS: int = 32

#: The host runner's portable address-space fallback, published beside the
#: cgroup limit — larger than :data:`MEM_MB` because jemalloc's address-space
#: *reservation* for the interpreter and polars exceeds two gigabytes even at a
#: small resident set, so a 2 GiB ``RLIMIT_AS`` lets the child die before it can
#: run the signal.  The two numbers are different facts about different
#: mechanisms, and a document that published either in the other's place is a
#: reviewer reading a cgroup limit out of an ``RLIMIT_AS`` default.
RUNNER_MEM_MB: int = 4096

#: A cpu time a cgroup would report for a run that outran its budget —
#: comfortably past it rather than a hair, so a test that means "rejected" is
#: not secretly a boundary test.
OVER_CPU_S: float = 44.0

#: A cpu time comfortably *inside* the budget — the run that was never in
#: danger.  The common case: most candidates consume a fraction of a second.
WITHIN_CPU_S: float = 12.5

#: The boundary case, and its own constant because the reading of it is the one
#: judgement in this law that could reasonably have gone the other way.
#: *Exceeding* is strict — the feature's own word — so a run that consumed
#: exactly its budget did **not** exceed it, and a test asserting that says so
#: by name.
AT_CPU_S: float = CPU_S

#: Memory peaks above and below the feature's limit, with room in them rather
#: than a hair past: ``OVER_MEM_MB`` is the first of the two numbers a breach
#: sentence prints.
OVER_MEM_MB: int = 3072
WITHIN_MEM_MB: int = 300
AT_MEM_MB: int = MEM_MB

#: Process counts above and below the limit, on the same terms.
OVER_PIDS: int = 64
WITHIN_PIDS: int = 4
AT_PIDS: int = PIDS

#: The shapes a *malformed* measurement arrives in: text (what a JSON document,
#: an environment variable or a §9.1 column hands one over as), bytes (no cgroup
#: counter reports its reading as bytes), a flag (``True`` is an ``int`` in
#: Python and is deliberately not a quantity here), a fractional count (no
#: counter produces one), and a negative one (not a budget under any reading).
TEXT_MEASUREMENT: str = "3072"
BYTES_MEASUREMENT: bytes = b"\x00\x0c\x00\x00"
FLAG_MEASUREMENT: bool = True
FRACTIONAL_MEM_MB: float = 3072.5
NEGATIVE_PIDS: int = -1

#: How far apart the two memory numbers are — *derived* from the pair above
#: rather than written down twice, so a test that means "the fallback is twice
#: the limit" compares against the same arithmetic the law's compiler does.
RUNNER_MEM_DRIFT_MB: int = RUNNER_MEM_MB - MEM_MB


def budget_run(
    *,
    cpu_s: Any = OVER_CPU_S,
    mem_mb: Any = WITHIN_MEM_MB,
    pids: Any = WITHIN_PIDS,
    node_id: str = "",
    component: str = "signal-sandbox",
) -> Any:
    """A fresh run as the cgroup law sees it — over its cpu budget unless told.

    Defaults to the *rejected* case on the cpu axis and inside the other two,
    because the feature's subject is a run that exceeded a limit and a breach
    sentence is only readable if it names which one: a test that means "this run
    was confined" passes ``cpu_s=WITHIN_CPU_S`` and says so, and one that means
    "it forked without bound" passes ``cpu_s=WITHIN_CPU_S, pids=OVER_PIDS``.

    Imported from :mod:`sandbox.budget` rather than re-spelled as a dict, for
    the reason :func:`timeout_run` gives: a run is not a *document* — the law
    reads it as an object carrying three measurements — and the tolerance for
    duck-typed subjects is exercised with explicit stand-ins in the law suite.

    ``cpu_s`` is positional-compatible with every measured field being ``None``
    on purpose: a caller testing the *unmeasured* refusal builds one with
    ``mem_mb=None`` or asks :func:`budget_run` with ``cpu_s=None`` for the
    unreadable subject.
    """
    from sandbox.budget import BudgetRun

    return BudgetRun(
        cpu_s=cpu_s,
        mem_mb=mem_mb,
        pids=pids,
        node_id=node_id,
        component=component,
    )


def budget_document(
    *,
    cpu_s: Any = CPU_S,
    mem_mb: Any = MEM_MB,
    pids: Any = PIDS,
    runner_mem_mb: Any = RUNNER_MEM_MB,
    policy: str = "sandbox-cgroup-limits",
    omit: tuple[str, ...] = (),
) -> dict[str, Any]:
    """A well-formed cgroup budget, drifted only where the caller says.

    ``policy`` and the four numbers are parameters rather than this builder
    reaching for the law's own constants, for the reason
    :func:`timeout_document` gives: a test that means "a document that does not
    declare itself" says exactly that, and a test that means "the committed
    policy" asks :func:`committed_budget_document` instead.  ``omit`` builds the
    *silent* document — the one that drops a limit entirely — which is a
    different refusal from a limit of the wrong value, and the law says so.

    The marker is written as the literal ``"sandbox-cgroup-limits"`` rather than
    read from :data:`sandbox.budget.BUDGET_POLICY_KIND`, deliberately: a document
    is an *input* to the compile, and a builder that had to import the module
    under test to be constructible would couple every drift test's premise to the
    thing being tested.
    """
    document: dict[str, Any] = {"policy": policy}
    for field, value in (
        ("cpu_s", cpu_s),
        ("mem_mb", mem_mb),
        ("pids", pids),
        ("runner_mem_mb", runner_mem_mb),
    ):
        if field not in omit:
            document[field] = value
    return document


def committed_budget_document() -> dict[str, Any]:
    """The committed artifact's shape: §5.2's three limits, and the marker.

    Shaped after the file on disk rather than read *from* it, for the reason
    :func:`committed_timeout_document` gives: the artifact's own tests read the
    file (:mod:`test_budget_artifact`), so a builder that read it too would make
    a drift in the file invisible to every test that meant to build a document
    instead.
    """
    return budget_document()


#: The three fields §5.2's limits clause names for this law, in the order the
#: committed artifact lists them — spelled as data so a test sweeping "every
#: measured field" has one list to sweep rather than three literals per test.
MEASURED_FIELDS: tuple[str, ...] = ("cpu_s", "mem_mb", "pids")

#: The runner's spelling for each of the three breaches, restated as data so the
#: law suite can pin them against feature 168's own vocabulary
#: (:data:`sandbox.failclass.SANDBOX_RUNNER_CLASSES`) in one cross-member test
#: rather than reading the law's constants back.  The precedence is the
#: cgroup's: a run that exhausted its cpu budget is throttled and killed
#: (``timeout``), one that allocated past ``memory.max`` is OOM-killed (``oom``),
#: and one that forked past ``pids.max`` had its ``fork`` fail outright
#: (``crash``).
CPU_FAIL_CLASS: str = "timeout"
MEMORY_FAIL_CLASS: str = "oom"
PIDS_FAIL_CLASS: str = "crash"


# ---------------------------------------------------------------------------
# Feature 160 — the seccomp syscall allowlist (app_spec.xml §5.2's syscall row)
#
# The sixth artifact-backed feature in this category, and the one whose subject
# is a *single call* rather than a run: §5.2's control table row is
# ``Syscalls | seccomp allowlist``, §3's zone map states what it serves
# ("Sandboxed: no network, no FS, seccomp, cgroup limits"), and §15's failure
# table names both the event and its consequence ("Sandbox escape attempt |
# seccomp violation | Kill, record fail_class, quarantine the node and its
# subtree").
#
# The syscall *names* below are spelled as data rather than imported from the
# committed artifact, for the reason :data:`CPU_S` gives one section up: a test
# that read the artifact would follow a rename of a term instead of catching
# one, and the point of the artifact suite is that the file's own content is
# what a deployment is held to.  Which of them the artifact *admits* is pinned
# by :mod:`test_syscalls_artifact`, not by this module.
# ---------------------------------------------------------------------------

#: A syscall the committed ceiling admits — the common case, and the one every
#: box is expected to make: ``read`` is how a signal reads its own payload.
ADMITTED_SYSCALL: str = "read"

#: Feature 160's own headline example, and the syscall §15's escape row is
#: really about: opening a file reaches the world §3's zone map denies the box
#: ("no network, no FS").  §5.2's isolation row states the same denial
#: structurally ("No mounts. Data arrives over IPC only."), so a box that
#: *called* ``openat`` is one whose filesystem posture failed rather than one
#: whose code was merely unusual.
DISALLOWED_SYSCALL: str = "openat"

#: The other three families a seccomp allowlist exists to deny, one per reason
#: the posture is stated: the network (a socket, denied by §3's "no network"),
#: process creation (a fork, which escapes the cgroup's ``pids.max`` accounting
#: and the box's whole containment), kernel entropy (a ``getrandom``, whose
#: absence is what makes a run's randomness come from feature 165's seed rather
#: than from the host), and the privilege/filter surface (a second ``seccomp``
#: filter, which is how a process would lift its own ceiling).
DISALLOWED_NETWORK_SYSCALL: str = "socket"
DISALLOWED_FORK_SYSCALL: str = "clone"
DISALLOWED_ENTROPY_SYSCALL: str = "getrandom"
DISALLOWED_ESCAPE_SYSCALL: str = "ptrace"
DISALLOWED_FILTER_SYSCALL: str = "seccomp"

#: §5.2's two denying action spellings, and the three that do not deny —
#: restated here as data so the compiler suite can name each one in a drift
#: without reading the law's tuples back.  ``kill`` is §15's own consequence
#: ("Kill, record fail_class, …"); ``errno`` is the other legal ceiling, which
#: fails the offending call instead of the process.
KILL_ACTION: str = "kill"
ERRNO_ACTION: str = "errno"

#: The three non-denying spellings that *look* like controls: each observes the
#: syscall and, by seccomp's own defaults, lets it through.  ``notify`` is the
#: near-miss worth a test of its own — a supervisor is handed the call and may,
#: and by default does, allow it — because a deployment running under it would
#: believe it was sandboxed.
LOG_ACTION: str = "log"
TRACE_ACTION: str = "trace"
NOTIFY_ACTION: str = "notify"
ALLOW_ACTION: str = "allow"

#: An action no version of seccomp has: the *unreadable* drift, which is a
#: different refusal from the widening one.  A filter's default is the action
#: every unlisted syscall meets, so a compiler that read an unrecognised
#: spelling as denying would be inventing a kernel behaviour from a string.
UNKNOWN_ACTION: str = "SIGKILL"

#: The spellings a *malformed* term arrives in: an upper-case name (what a
#: documentation table or an OCI profile may carry), a dotted module term (a
#: ceiling from feature 167's law arriving in this one's grammar), a padded
#: spelling (which would match nothing if taken literally), a leading
#: underscore (not a kernel spelling), an empty string, and a ``None``.
UPPERCASE_TERM: str = "OpenAt"
DOTTED_TERM: str = "os.open"
PADDED_TERM: str = "  read  "
LEADING_UNDERSCORE_TERM: str = "_exit"
EMPTY_TERM: str = ""

#: A syscall name that is well-formed and that no real kernel registers — the
#: term that proves the *grammar* and the *membership* are different checks: it
#: compiles into a document, and it is still not admitted for any process that
#: never names it.
INVENTED_SYSCALL: str = "zzz_not_a_syscall"


def syscall_attempt(
    *,
    syscall: Any = DISALLOWED_SYSCALL,
    node_id: str = "",
    component: str = "signal-sandbox",
) -> Any:
    """A fresh attempt as the seccomp law sees it — outside the ceiling unless told.

    Defaults to the *rejected* case, because the feature's subject is a process
    attempting a *disallowed* syscall and a refusal sentence is only readable if
    it names which one: a test that means "this call was admitted" passes
    ``syscall=ADMITTED_SYSCALL`` and says so, and one that means "nothing this
    law can read was offered" passes ``syscall=None``.

    Imported from :mod:`sandbox.syscalls` rather than re-spelled as a dict, for
    the reason :func:`budget_run` gives: an attempt is not a *document* — the law
    reads it as an object carrying a ``syscall`` name — and the tolerance for
    duck-typed subjects is exercised with explicit stand-ins in the law suite.
    """
    from sandbox.syscalls import SyscallAttempt

    return SyscallAttempt(syscall=syscall, node_id=node_id, component=component)


def syscalls_document(
    *,
    default_action: Any = KILL_ACTION,
    allow: Any = None,
    policy: str = "sandbox-syscalls",
    omit: tuple[str, ...] = (),
) -> dict[str, Any]:
    """A well-formed seccomp ceiling, drifted only where the caller says.

    ``policy``, ``default_action`` and the term list are parameters rather than
    this builder reaching for the law's own constants, for the reason
    :func:`budget_document` gives: a test that means "a document whose default
    does not deny" says exactly that, and a test that means "the committed
    ceiling" asks :func:`committed_syscalls_document` instead.  ``omit`` builds
    the *silent* document — the one that drops a required key entirely — which
    is a different refusal from one carrying a wrong value, and the law says so.

    The default term list is a small, legally-shaped ceiling rather than the
    committed forty: a drift test varies one thing, and a term list copied from
    the artifact would make every such test's premise depend on the file it is
    testing.  ``exit_group`` is in it because a ceiling with no way for the
    process to end is refused by construction — the builder's default has to be
    *compilable* or every caller would have to remember to add a termination.
    """
    from sandbox.syscalls import TERMINATION_SYSCALLS

    document: dict[str, Any] = {"policy": policy}
    if "default_action" not in omit:
        document["default_action"] = default_action
    if "allow" not in omit:
        terms = (
            [ADMITTED_SYSCALL, "write", *sorted(TERMINATION_SYSCALLS)]
            if allow is None
            else allow
        )
        document["allow"] = list(terms)
    return document


def committed_syscalls_document() -> dict[str, Any]:
    """The committed artifact's shape: a denying default and a usable ceiling.

    Shaped after the file on disk rather than read *from* it, for the reason
    :func:`committed_budget_document` gives: the artifact's own tests read the
    file (:mod:`test_syscalls_artifact`), so a builder that read it too would
    make a drift in the file invisible to every test that meant to build a
    document instead.
    """
    return syscalls_document()


#: The syscall names the committed artifact is *expected* to admit, spelled as
#: data so the artifact suite compares two literal lists rather than the file
#: against itself.  A name moving in or out of this tuple is a posture change a
#: reviewer should have to make deliberately — the reading feature 167's
#: ``COMMITTED_ALLOWLIST_TERMS`` takes of its own ceiling.
COMMITTED_SYSCALL_TERMS: tuple[str, ...] = (
    # The data plane: a signal reads its payload and writes its answer.
    "read",
    "write",
    "readv",
    "writev",
    "close",
    "lseek",
    "fcntl",
    "dup",
    # Readiness: waiting on an fd rather than spinning, which the wall clock
    # budget depends on — a busy loop would consume cpu past feature 162's cap.
    "pipe2",
    "poll",
    "ppoll",
    "epoll_create1",
    "epoll_ctl",
    "epoll_wait",
    "eventfd2",
    # The interpreter's own memory management.
    "brk",
    "mmap",
    "munmap",
    "mprotect",
    "madvise",
    "mremap",
    "membarrier",
    "rseq",
    # Signal handling, which the language runtime installs at startup.
    "rt_sigaction",
    "rt_sigprocmask",
    "rt_sigreturn",
    "sigaltstack",
    # Runtime bookkeeping: the futex plane a thread pool needs, plus identity
    # and limits reads that reach no world.
    "futex",
    "sched_yield",
    "getpid",
    "gettid",
    "set_tid_address",
    "set_robust_list",
    "arch_prctl",
    "prlimit64",
    "uname",
    # Clocks only.  ``getrandom`` is deliberately absent: a run's randomness is
    # feature 165's seed, drawn by the dispatcher rather than by the box.
    "clock_gettime",
    "nanosleep",
    # The way out.  Required by the compiler — a filter that admits nothing
    # terminates every candidate at its first instruction.
    "exit",
    "exit_group",
)

#: The families the committed artifact must **not** admit, and the reason each
#: is absent — the negative half of the ceiling, which is what makes the
#: positive list a sandbox rather than a description.  Spelled as data so the
#: artifact suite sweeps one tuple rather than re-deriving the omissions from
#: the positive list (which would pass for an artifact that admitted nothing).
FORBIDDEN_SYSCALL_TERMS: tuple[str, ...] = (
    # The filesystem family — §5.2: "No mounts. Data arrives over IPC only."
    "open",
    "openat",
    "openat2",
    "creat",
    "stat",
    "fstat",
    "lstat",
    "newfstatat",
    "statx",
    "access",
    "getdents64",
    "mkdir",
    "unlink",
    "rename",
    "chmod",
    "chdir",
    # The network family — §5.2: "Namespace with no interfaces. Not a firewall
    # rule."  A socket call cannot be what enforces that, and the namespace is.
    "socket",
    "socketpair",
    "connect",
    "bind",
    "listen",
    "accept",
    "accept4",
    "sendto",
    "recvfrom",
    "sendmsg",
    "recvmsg",
    "setsockopt",
    "getsockopt",
    # Process creation — a fork escapes the containment entirely and is not
    # accounted by feature 162's ``pids.max``.
    "clone",
    "clone3",
    "fork",
    "vfork",
    "execve",
    "execveat",
    # The escape surface §15's row is about.
    "ptrace",
    "process_vm_readv",
    "process_vm_writev",
    "kcmp",
    "pidfd_open",
    "pidfd_getfd",
    # Kernel entropy — the box draws its randomness from feature 165's seed.
    "getrandom",
    "getentropy",
    # Namespace and filter manipulation: how a confined process would lift its
    # own ceiling or leave the namespace that denies it a network.
    "unshare",
    "setns",
    "mount",
    "umount2",
    "pivot_root",
    "chroot",
    "seccomp",
    "prctl",
    "capset",
    "personality",
    # Signalling out of the box, and the device/argument surface a name-based
    # allowlist cannot bound.
    "kill",
    "tgkill",
    "tkill",
    "ioctl",
)


# Feature 161 — the quarantine law (app_spec.xml §15).  The tree is seeded here
# as *rows* rather than through a store, because feature 97's `node` table is the
# caller's to fetch and this member opens no database: a test that means "the
# branch from this node" says which edges exist by handing them in.
QUARANTINE_CAMPAIGN: str = "campaign-9f2e"
OTHER_QUARANTINE_CAMPAIGN: str = "campaign-4a71"
QUARANTINE_ROOT_ID: str = "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
QUARANTINE_CHILD_ID: str = "1b2c3d4e-5f6a-4b7c-8d9e-0f1a2b3c4d5e"
QUARANTINE_GRANDCHILD_ID: str = "2c3d4e5f-6a7b-4c8d-9e0f-1a2b3c4d5e6f"
QUARANTINE_GREATGRANDCHILD_ID: str = "3d4e5f6a-7b8c-4d9e-8f0a-1b2c3d4e5f6a"
QUARANTINE_SIBLING_ID: str = "4e5f6a7b-8c9d-4e0f-9a1b-2c3d4e5f6a7b"
OTHER_CAMPAIGN_ROOT_ID: str = "5f6a7b8c-9d0e-4f1a-8b2c-3d4e5f6a7b8c"
OTHER_CAMPAIGN_CHILD_ID: str = "6a7b8c9d-0e1f-4a2b-9c3d-4e5f6a7b8c9d"


def node_row(
    node_id: str,
    *,
    parent_id: str | None = None,
    campaign_id: str = QUARANTINE_CAMPAIGN,
    theme_root: str = "test-theme",
    depth: int = 0,
) -> dict[str, Any]:
    """One feature-97 ``node`` row, as a caller's fetch hands it over.

    The five structural columns migration ``0118_node_table`` declares, with the
    class column absent: a node row before anything has been recorded about it is
    the state a fresh quarantine is written onto, and a test that means "this node
    already carries a class" passes ``record`` to :func:`quarantine_record`.
    """
    return {
        "id": node_id,
        "parent_id": parent_id,
        "campaign_id": campaign_id,
        "theme_root": theme_root,
        "depth": depth,
    }


def quarantine_record(
    node_id: str = QUARANTINE_ROOT_ID,
    *,
    parent_id: str | None = None,
    campaign_id: str = QUARANTINE_CAMPAIGN,
    fail_class: Any = None,
    quarantined_at: Any = None,
) -> dict[str, Any]:
    """A node row as the *caller's record* — the mapping :meth:`Quarantine.mark` writes into.

    Distinct from :func:`node_row` because the two are different things in this
    law's vocabulary: ``node_row`` is what a tree is *built* from, and this is
    what a halt is *written to*.  ``fail_class`` and ``quarantined_at`` are
    omitted rather than set to ``None`` when they are not asked for, so a test
    that means "this node carries no class yet" produces a row without the key —
    which is the shape a fresh §9.1 row has.
    """
    record: dict[str, Any] = {
        "id": node_id,
        "parent_id": parent_id,
        "campaign_id": campaign_id,
    }
    if fail_class is not None:
        record["fail_class"] = fail_class
    if quarantined_at is not None:
        record["quarantined_at"] = quarantined_at
    return record


def quarantine_rows(
    *,
    campaign_id: str = QUARANTINE_CAMPAIGN,
    depth: int = 3,
) -> list[dict[str, Any]]:
    """One campaign's tree: root → child → grandchild → great-grandchild, plus a sibling.

    ``depth`` is how many *descendants* hang below the root, so ``depth=0`` is a
    bare root and ``depth=1`` is a root with one child — the two ends a
    quarantine's width test needs; the suite's default of 3 is root → child →
    grandchild → great-grandchild.  A *sibling* branch hangs off the root, because
    the property under test is that a halt starting at the child takes two nodes
    and leaves the sibling alone: a tree that is one chain cannot tell "the
    subtree" from "everything below the root".
    """
    rows: list[dict[str, Any]] = [node_row(QUARANTINE_ROOT_ID, campaign_id=campaign_id)]
    chain = [
        (QUARANTINE_CHILD_ID, QUARANTINE_ROOT_ID),
        (QUARANTINE_GRANDCHILD_ID, QUARANTINE_CHILD_ID),
        (QUARANTINE_GREATGRANDCHILD_ID, QUARANTINE_GRANDCHILD_ID),
    ]
    for index, (node_id, parent_id) in enumerate(chain[: max(depth, 0)], start=1):
        rows.append(
            node_row(node_id, parent_id=parent_id, campaign_id=campaign_id, depth=index)
        )
    rows.append(
        node_row(QUARANTINE_SIBLING_ID, parent_id=QUARANTINE_ROOT_ID, campaign_id=campaign_id, depth=1)
    )
    return rows


def two_campaign_rows() -> list[dict[str, Any]]:
    """Two campaigns' rows in one fetch, with one branch crossing between them.

    The leak test: ``OTHER_CAMPAIGN_CHILD_ID``'s ``parent_id`` points at
    ``QUARANTINE_CHILD_ID``, so the edge exists but the campaign differs.  A
    closure that walked edges without checking the campaign would halt a node in
    a campaign nobody asked about — which is why the scope is read from the
    violating node's own row rather than taken as a parameter.
    """
    rows = quarantine_rows()
    rows.append(node_row(OTHER_CAMPAIGN_ROOT_ID, campaign_id=OTHER_QUARANTINE_CAMPAIGN))
    rows.append(
        node_row(
            OTHER_CAMPAIGN_CHILD_ID,
            parent_id=QUARANTINE_CHILD_ID,
            campaign_id=OTHER_QUARANTINE_CAMPAIGN,
            depth=1,
        )
    )
    return rows


def cyclic_rows(
    *,
    campaign_id: str = QUARANTINE_CAMPAIGN,
) -> list[dict[str, Any]]:
    """Two nodes that name each other — the tree a ``UNION ALL`` recursion hangs on.

    The fault this law refuses rather than guesses at: a recursive CTE over these
    edges never terminates, so a closure walked in SQL cannot produce the refusal
    at all.  Walking the edges in Python bounds the work by the rows handed in,
    which is what makes this a :class:`~sandbox.errors.QuarantineTreeError` an
    operator can act on.
    """
    return [
        node_row(QUARANTINE_CHILD_ID, parent_id=QUARANTINE_GRANDCHILD_ID, campaign_id=campaign_id),
        node_row(QUARANTINE_GRANDCHILD_ID, parent_id=QUARANTINE_CHILD_ID, campaign_id=campaign_id, depth=1),
    ]


def self_parented_rows(
    *,
    campaign_id: str = QUARANTINE_CAMPAIGN,
) -> list[dict[str, Any]]:
    """One node that is its own parent — the shortest cycle, refused the same way."""
    return [node_row(QUARANTINE_ROOT_ID, parent_id=QUARANTINE_ROOT_ID, campaign_id=campaign_id)]


def quarantine_violation_from_gate(
    *,
    syscall: str = DISALLOWED_SYSCALL,
    default_action: str = KILL_ACTION,
    node_id: str = QUARANTINE_CHILD_ID,
    component: str = SIGNAL_SANDBOX,
) -> Any:
    """A real violation, taken from feature 160's gate rather than re-spelled.

    The handoff under test is the one the gate actually publishes, so this builds
    a fresh :class:`~sandbox.syscalls.SandboxSyscalls` over a compiled ceiling,
    asks it about ``syscall``, and returns the *decision* — the object
    :func:`sandbox.quarantine.quarantine_violation` is handed in production.  A
    builder that constructed a ``Commitment`` directly would test a shape this law
    tolerates rather than the value it is actually given.

    ``default_action`` is what the *commitment's* ``action`` is read from —
    feature 160's gate does not take an action per attempt, it reads the one the
    ceiling denies by — so a test that means "the errno path that let the process
    carry on" compiles a ceiling denying by ``errno`` and passes
    ``default_action=ERRNO_ACTION``.  The class that comes back is
    ``sandbox_escape`` in both cases, which is the point: the *fate* differs and
    the class does not, and the commitment's ``killed`` property is what makes
    the difference readable at the seam.
    """
    from sandbox.syscalls import SandboxSyscalls, compile_syscalls_policy

    ceiling = compile_syscalls_policy(
        syscalls_document(default_action=default_action)
    )
    gate = SandboxSyscalls(ceiling)
    return gate.check(syscall_attempt(syscall=syscall, node_id=node_id, component=component))
