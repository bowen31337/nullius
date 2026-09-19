"""``contract_version`` — the signal ABI's version stamp (feature 15).

Feature 15 of app_spec.xml: "System versions the signal ABI with a
``contract_version`` constant that every stored node persists alongside its
code hash."

The constant itself is declared in :mod:`contract` (next to the ABI it
versions, so a persisted node's stamp can never drift from the code it
describes).  This module is the other half of the feature: what it *means* to
persist it, and the check a reader runs to find out what an old stamp was
written against.

Why the stamp exists at all
---------------------------

A stored node is a *code hash* plus a *contract version*, and the two answer
different questions.  The code hash answers "is this the same source?".  The
contract version answers "was this source written against the same ABI?" — the
entrypoint name, the window it is handed, the shape of the vector it returns
(feature 11).  Without the second, an ABI change is invisible: two nodes with
different code hashes look like two experiments, when the truth may be that
the same experiment was run twice against signatures that no longer agree.
Every comparison downstream of the tree — paired ΔIR, deduplication by
``code_hash``, the replay path — silently assumes the two are commensurable,
and the stamp is the only place that assumption is recorded.  So it is
persisted *beside* the code hash rather than derived from it.

What this module refuses to do
------------------------------

It does not decide what happens to a node whose stamp is stale.  Features 97
through 102 own the ``node`` table and every column on it; the writer that
actually persists a row is theirs, and no code in ``discovery/`` exists yet in
this repository.  What this module provides is the *vocabulary and the check*
those writers use: the field name to persist under, the canonical stamp, a
node-shaped record you can build and read back, and :func:`compare` — the
question "is a stored stamp the ABI this build speaks?" answered as a value
(``compatible`` / ``stale`` / ``malformed``) rather than an exception, because
a reader of a five-month-old tree must be able to report a mismatch without
failing to read the tree.

The comparison is deliberately *not* a compatibility range.  Nothing in the
ABI is additive-only today — the entrypoint is one function with two arguments
and one return shape — so a version predicate with a lower bound and no upper
bound would be a promise this package cannot keep, and the first ABI change
would quietly read as compatible.  A single version, compared for equality, is
the honest predicate; when the ABI does grow a compatible extension, that will
be a deliberate edit here with a test that says so.

Version-string discipline
-------------------------

The stamp is a dotted numeric string (``"0.1.0"``, and ``"1"`` or ``"2.3"``
parse too), never a date, a git sha or a free-form label.  It has to be
comparable by something other than string equality — ordering two stamps is
what lets a caller say "this node is older than the current ABI" rather than
merely "different" — and a git sha cannot be ordered while a date cannot be
declared.  :func:`parse_contract_version` reads one, and refuses anything that
is not numeric components, because a stamp that silently fails to parse is a
provenance record that silently stops being checkable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Mapping

if TYPE_CHECKING:  # pragma: no cover - typing only
    from . import MarketWindow

__all__ = [
    "CONTRACT_VERSION_FIELD",
    "NODE_ABI_RECORD_FIELDS",
    "Compatibility",
    "ContractVersionError",
    "NodeAbiRecord",
    "compare",
    "contract_version",
    "describe_contract_version",
    "node_abi_record",
    "parse_contract_version",
    "read_node_abi_record",
    "require_supported_contract_version",
]

#: The field name a stored node carries its ABI stamp under.
#:
#: Pinned to the spelling the composed component already advertises
#: (``contract.build_market_window_contract`` returns ``{"contract_version":
#: ...}``), so the record a writer persists and the record the factory
#: composes name the same fact the same way.  A writer that invented its own
#: column name would produce a row this module cannot read, and the drift
#: would be invisible until someone tried.
CONTRACT_VERSION_FIELD = "contract_version"

#: The fields that make up a node's ABI record, in the order they are read.
#:
#: Two, and only two, on purpose: the code hash says what was written and the
#: contract version says what it was written *against*.  Anything else a node
#: is stamped with (``evaluator_hash``, ``snapshot_hash``,
#: ``cost_model_hash`` — features 97-102) is provenance of the *evaluation*,
#: not of the ABI, and folding it in here would make this record change for
#: reasons that have nothing to do with the contract.
NODE_ABI_RECORD_FIELDS = (CONTRACT_VERSION_FIELD, "code_hash")


class ContractVersionError(ValueError):
    """A contract version that cannot be read as the numeric stamp it claims to be.

    Raised only by :func:`parse_contract_version` (and the callers that
    require a parsed stamp).  Reading a *stored* node never raises for a bad
    stamp: :func:`compare` reports ``malformed`` instead, because a reader
    auditing an old tree must be able to say "this row's stamp is unusable"
    without the audit itself falling over.
    """


@dataclass(frozen=True)
class Compatibility:
    """The answer to "is this stored stamp the ABI that is running?".

    A value, not an exception, for the same reason the signal validators
    return problem lists: the caller is the one that knows what a mismatch
    costs — a replay may refuse the node, an audit may merely flag it, a
    dedup pass may treat it as a different experiment — and a check that
    raised would steal that decision.

    Frozen and hashable, but deliberately not *ordered*: :attr:`stored` is
    ``None`` for a malformed stamp, so a generated ``__lt__`` would raise
    ``TypeError`` on exactly the rows an audit most wants to sort. A caller
    that needs an order sorts on :attr:`status` itself, which is a string for
    every verdict.

    Attributes
    ----------
    status:
        ``"compatible"``, ``"stale"`` or ``"malformed"``.  ``stale`` covers
        both directions (older and newer than the current ABI), which is
        deliberate: a stamp from the future is not *more* compatible than one
        from the past, and a caller that wants the direction reads
        :attr:`direction`.
    current:
        The ABI this process speaks.
    stored:
        The stamp as it was read off the node.
    direction:
        ``"same"``, ``"older"`` or ``"newer"`` for a stamp that parsed,
        ``None`` for one that did not.  ``older``/``newer`` is relative to
        :attr:`current`.
    message:
        One human-readable sentence, suitable for a run record.
    """

    status: str
    current: str
    stored: str | None
    direction: str | None
    message: str

    @property
    def compatible(self) -> bool:
        """Whether the stored stamp is exactly the ABI that is running."""
        return self.status == "compatible"


def _current_contract_version() -> str:
    """Read :data:`contract.CONTRACT_VERSION` from the package namespace.

    Imported inside the call rather than at module scope because
    :mod:`contract.version` is imported *by* the package ``__init__``, and
    reaching back for a name the package has not bound yet would make the two
    imports order-dependent — ``from . import CONTRACT_VERSION`` at module
    scope raises during the package's own initialization.  :mod:`contract.payload`
    reads the same constant the same way, for the same reason.  A relative
    import (rather than ``import contract``) is what keeps this working when
    the member is reached under the loader's synthetic scan name and its
    ``src`` directory is no longer on ``sys.path``.

    The lookup resolves against the live package object on every call, not a
    copy taken at import, so a test that monkeypatches
    ``contract.CONTRACT_VERSION`` to simulate an ABI change is seen by every
    function here — a module-level cache would make the one thing this module
    exists to compare untestable.
    """
    from . import CONTRACT_VERSION

    return CONTRACT_VERSION


def contract_version() -> str:
    """The current signal ABI version, as a value.

    Exposed as a function beside the :data:`contract.CONTRACT_VERSION`
    constant for the same reason the other contract accessors are: a caller
    asking "what ABI does this build speak" gets one answer from one place,
    without having to know a module global's name.  It takes no arguments by
    design — which ABI is current is a property of the deployed contract, not
    of the call.
    """
    return _current_contract_version()


def describe_contract_version() -> dict[str, Any]:
    """What the current ``contract_version`` stamps, as a plain record.

    The stamp on its own is a string a reader cannot interpret: it says a node
    was written against ``"0.1.0"`` but not what ``"0.1.0"`` meant.  This
    returns the pieces the ABI is actually made of — the version, the
    ``module:attribute`` name of the window every signal is evaluated against,
    and the entrypoint the sandbox executes — so a run can record what it was
    running against after the fact, from data rather than from a git checkout.

    Read from the package namespace rather than from module-level imports for
    the same reason :func:`_current_contract_version` is: at module scope the
    imports would be order-dependent against this package's own ``__init__``.
    """
    from . import CONTRACT_VERSION, MARKET_WINDOW_ABI, SIGNAL_ENTRYPOINT

    return {
        CONTRACT_VERSION_FIELD: CONTRACT_VERSION,
        "market_window": MARKET_WINDOW_ABI,
        "entrypoint": SIGNAL_ENTRYPOINT,
    }


def parse_contract_version(version: Any) -> tuple[int, ...]:
    """Parse a dotted numeric version string into its components.

    ``"0.1.0"`` becomes ``(0, 1, 0)``; ``"1"`` becomes ``(1,)``.  Components
    are compared numerically rather than as strings, so ``(0, 10, 0)`` orders
    after ``(0, 9, 0)`` — the bug a string comparison of ``"0.10.0"`` against
    ``"0.9.0"`` would introduce and hide.

    Raises :class:`ContractVersionError` on anything that is not one or more
    non-negative integer components: a version is a declaration, and one that
    cannot be ordered is not a declaration this system can act on.  The
    refusal is loud here (rather than a ``None`` return) because the callers
    that parse are assert-time and writer-time callers, where an unusable
    stamp is a bug in the immediate caller — a *reader* of stored data wants
    :func:`compare`, which never raises.
    """
    if isinstance(version, bool) or not isinstance(version, str):
        raise ContractVersionError(
            f"contract version must be a string, got {type(version).__name__}; "
            "the stamp is a dotted numeric string like '0.1.0'"
        )
    text = version.strip()
    if not text:
        raise ContractVersionError(
            "contract version is empty; the stamp must be a dotted numeric "
            "string like '0.1.0'"
        )
    parts = text.split(".")
    for part in parts:
        if not part.isdigit():
            raise ContractVersionError(
                f"contract version {version!r} is not a dotted numeric string: "
                f"{part!r} is not a non-negative integer component. The stamp "
                "is never a date, a git sha or a free-form label — it has to "
                "be orderable so a stale node can be told from a current one"
            )
    return tuple(int(part) for part in parts)


def compare(stored: Any, *, current: str | None = None) -> Compatibility:
    """Compare a *stored* ``contract_version`` against the running ABI.

    The check a reader runs over a persisted node: given the stamp a row
    carries, is it the ABI this build speaks?  Returns a
    :class:`Compatibility` and never raises — a row with an unusable stamp
    reports ``malformed`` with its reason, because an audit must be able to
    describe a bad row rather than abort on it.

    ``current`` defaults to :data:`contract.CONTRACT_VERSION`, so a caller
    comparing against the ABI that is actually deployed passes nothing; it is
    a parameter only so a test (or a migration tool reasoning about an
    *older* build) can name the other side of the comparison explicitly.
    """
    current_version = _current_contract_version() if current is None else current
    try:
        current_parts = parse_contract_version(current_version)
    except ContractVersionError as exc:  # pragma: no cover - the constant is ours
        raise ContractVersionError(
            f"the running contract version {current_version!r} is not a "
            f"readable stamp, which is a bug in this build: {exc}"
        ) from exc

    if stored is None:
        return Compatibility(
            status="malformed",
            current=current_version,
            stored=None,
            direction=None,
            message=(
                "node records no contract_version, so the ABI its source was "
                "written against is unknown; a node without the stamp cannot "
                "be compared against any other node or replayed"
            ),
        )

    try:
        stored_parts = parse_contract_version(stored)
    except ContractVersionError as exc:
        return Compatibility(
            status="malformed",
            current=current_version,
            stored=stored if isinstance(stored, str) else None,
            direction=None,
            message=f"node records an unreadable contract_version: {exc}",
        )

    if stored_parts == current_parts:
        return Compatibility(
            status="compatible",
            current=current_version,
            stored=stored,
            direction="same",
            message=(
                f"node was written against contract_version {stored} — the "
                "ABI this build speaks"
            ),
        )

    older = stored_parts < current_parts
    return Compatibility(
        status="stale",
        current=current_version,
        stored=stored,
        direction="older" if older else "newer",
        message=(
            f"node was written against contract_version {stored}, which is "
            f"{'older' if older else 'newer'} than the running ABI "
            f"{current_version}; its code hash describes source aimed at a "
            "different signal ABI, so scores computed from it are not "
            "commensurable with current ones"
        ),
    )


def require_supported_contract_version(version: Any) -> str:
    """Return ``version`` if it is the running ABI, else raise.

    The strict half of :func:`compare`, for the callers where proceeding on a
    mismatch is meaningless rather than merely noteworthy — most concretely a
    sandbox about to execute a node's code: running source written against a
    different entrypoint contract produces a failure far from its cause, so
    the refusal belongs at the boundary where the stamp is known.

    A ``malformed`` stamp raises too; there is nothing to execute under a
    version that cannot be read.
    """
    verdict = compare(version)
    if not verdict.compatible:
        raise ContractVersionError(verdict.message)
    assert verdict.stored is not None  # compatible implies a readable stamp
    return verdict.stored


@dataclass(frozen=True)
class NodeAbiRecord:
    """The ABI half of a stored node: its ``contract_version`` and its code hash.

    Feature 15's sentence made concrete — "every stored node persists [the
    contract version] alongside its code hash".  This is that pair as one
    value, with the two rules that make persisting it meaningful:

    * **both are required.**  A record with a code hash and no stamp is
      unreadable provenance (you cannot tell which ABI the source was written
      against), and a stamp with no code hash names a contract but not the
      source.  Neither is a partial record worth storing, so neither
      constructs.
    * **the stamp is readable.**  The version is parsed at construction, so a
      writer cannot persist a stamp that no reader could compare.  This is the
      one place the parse is enforced eagerly — writers are exactly the callers
      who can still do something about it.

    Nothing here validates the code hash's *algorithm*: whether it is a sha256
    of the source is features 97-102's contract and the sandbox's business.
    What this class pins is that a code hash is present and non-empty, so the
    pair travels together.
    """

    contract_version: str
    code_hash: str

    def __post_init__(self) -> None:
        parse_contract_version(self.contract_version)
        if not isinstance(self.code_hash, str) or not self.code_hash.strip():
            raise ValueError(
                "a node's ABI record requires a non-empty code_hash: the "
                "contract_version says which ABI the source was written "
                "against, and the code hash says which source"
            )

    def as_dict(self) -> dict[str, str]:
        """The record as the plain mapping a writer persists.

        Keyed by :data:`CONTRACT_VERSION_FIELD` and ``"code_hash"`` — the
        spellings the composed component and features 97-102 already use — so
        the dict needs no translation at the storage boundary.
        """
        return {
            CONTRACT_VERSION_FIELD: self.contract_version,
            "code_hash": self.code_hash,
        }

    def compatibility(self, *, current: str | None = None) -> Compatibility:
        """Whether this node's stamp is the running ABI (see :func:`compare`)."""
        return compare(self.contract_version, current=current)


def node_abi_record(
    window: "MarketWindow | None" = None,
    *,
    code_hash: str,
    contract_version: str | None = None,
) -> NodeAbiRecord:
    """Build a node's ABI record, defaulting the stamp to the running ABI.

    The entry point a node writer calls: it hands over the code hash it
    computed and gets back the pair to persist, stamped with the ABI this
    build speaks unless the caller is deliberately recording an older one
    (a migration re-stamping rows, a backfill of a node executed elsewhere).

    ``window`` is accepted and ignored.  It is there so the call reads at the
    site as what it is — the stamp describes *this* contract, the one that
    produced the window the node's signal was evaluated against — and because
    a caller holding the window it just ran should be able to say so rather
    than reconstruct that fact from the clock.  Nothing is read off it: the
    window carries no version of its own by design (the ABI version belongs to
    the code, not to the data; see the note in the module docstring of
    :mod:`contract.payload` on why the payload version is a separate number).

    ``contract_version`` is defaulted on ``None`` alone, never on falsiness.
    "I did not name a version" and "I named an empty one" are different
    statements, and an ``or`` here would collapse them — silently stamping the
    running ABI onto a caller who passed ``""``, which is precisely the
    quietly-uncheckable provenance this module exists to refuse.  An empty or
    unreadable explicit stamp reaches :class:`NodeAbiRecord` and is refused
    there, by name.
    """
    del window  # accepted for call-site clarity; the stamp comes from the build
    return NodeAbiRecord(
        contract_version=(
            _current_contract_version() if contract_version is None
            else contract_version
        ),
        code_hash=code_hash,
    )


def read_node_abi_record(record: Mapping[str, Any]) -> NodeAbiRecord:
    """Read a persisted node's ABI pair back out of its row or dict.

    The inverse of :meth:`NodeAbiRecord.as_dict`, and deliberately strict on
    the same two fields: a writer that persisted the pair under different
    names, or dropped one, produces a row that cannot be read back, and the
    failure is reported here by name rather than surfacing later as an
    unexplained ``KeyError`` inside a comparison loop.

    A column that is *present but NULL* is refused with that same message
    rather than being handed to the constructor.  A NULL stamp from the
    database is the ordinary state of a row written before the stamp existed
    (or by a writer whose column defaults to NULL), not a programming error —
    so it is reported as "this row does not carry the pair", which is what it
    is, instead of escaping as a bare
    :class:`ContractVersionError` about a version string.  The tolerant answer
    for exactly this row is :func:`compare`, which reports ``malformed``.
    """
    if not isinstance(record, Mapping):
        raise TypeError(
            "a stored node's ABI record is a mapping carrying "
            f"{CONTRACT_VERSION_FIELD!r} and 'code_hash'; got "
            f"{type(record).__name__}"
        )
    missing = [
        field
        for field in NODE_ABI_RECORD_FIELDS
        if field not in record or record[field] is None
    ]
    if missing:
        raise KeyError(
            "stored node is missing its ABI record field(s) "
            f"{missing}: feature 15 persists the contract_version alongside "
            "the code hash, so a row carrying only one of them does not say "
            "which ABI its source was written against"
        )
    return NodeAbiRecord(
        contract_version=record[CONTRACT_VERSION_FIELD],
        code_hash=record["code_hash"],
    )
