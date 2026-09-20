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

from typing import Any

from sandbox import IMPORTS_POLICY_KIND, POLICY_KIND

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
