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
from typing import Any

import polars as pl
import pyarrow as pa
from contract import MarketWindow
from contract.signal import validate_signal_return
from sandbox import IMPORTS_POLICY_KIND, POLICY_KIND, encode_scores

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
