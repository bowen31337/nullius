"""Feature 205's law: a proposal is adopted only as a conforming signal.

app_spec.xml, "Hypothesis Authoring Agent", feature 205: *System writes a
signal function conforming to the declared contract, which returns source
that the sandbox executes.*  docs/nullius-tech-architecture.md §5.1 declares
the contract the sentence points at — the one entrypoint, spelled out —

    def signal(ctx: MarketWindow, seed: int) -> pl.Series:

— and §5.2 shows what happens to what the agent wrote::

    result = sandbox.run(
        entrypoint="signal",
        code=node.code,
        ...
    )

The sentence decomposes into three claims, and this module is each of them:

* **the declared contract** — the entrypoint's name, its two parameters and
  the return shape are *declared*, not agreed, and the declaration lives in
  :mod:`contract.signal` rather than here.  This member reads it
  (:func:`SignalContract.signature`, :meth:`SignalContract.declaration`) and
  never restates it: a second spelling of ``signal(ctx, seed)`` in the agent's
  own member would be a second thing to keep in sync with the ABI every stored
  node is stamped against, and feature 15 already made that stamp a
  contract-versioned artifact.  What this member owns is the *seam* — the
  thing that answers "does this proposal conform?" — not the shape it checks
  for.

* **writes a signal function conforming to** it — adoption is a judgement, and
  it is made *before* the proposal becomes history.  :meth:`SignalContract.
  adopt` hands the agent's text to
  :func:`contract.validate_signal_signature`, which compiles it and inspects
  the resulting function's parameters, and answers with a
  :class:`SourceAdoption`.  A source that does not conform is not the node the
  campaign thought it had: §9.1's tree row carries ``code_hash`` and §12's
  replay is bit-reproducible *because* the entrypoint is fixed, so a proposal
  the box cannot invoke is refused here rather than persisted and discovered
  at replay time.

* **which returns source that the sandbox executes** — what adoption yields is
  *source*, in the sense §5.2 means: the exact text ``node.code`` will hold,
  whose sha256 is the ``code_hash`` the tree persists, unchanged by this
  module.  Adoption does not rewrite, normalize, wrap or reformat the agent's
  text — a member that tidied a proposal "into conformance" would be
  authoring it, and feature 205's subject is the agent, not this member — so
  :meth:`SourceAdoption.require` returns the text the validator was handed,
  and :meth:`SourceAdoption.abi_record` stamps that same text with the ABI it
  conformed to.

**Why adoption raises nothing, and what raises instead.**
:meth:`SignalContract.adopt` returns a value, the shape every gate in this
workspace takes (:meth:`sandbox.SandboxSeed.check`,
:meth:`sandbox.sandbox_imports`, the evaluator's ``SignalSandbox.run``): a
campaign driver diagnoses *why* a branch's proposal did not conform — feature
209's distinction between a flawed core mechanism and a sound idea undermined
by a located bug — and a gate that raised would have taken that decision from
the caller.  :meth:`SourceAdoption.require` is the bridge for the caller on
its last line before persisting, and only there does
:class:`~signal_agent.errors.AgentSourceError` appear.

**The optional box screen, and why it is a parameter rather than a law.**
Feature 167 gives the sandbox an import allowlist and §5.2's box refuses a
submission importing outside it.  That refusal is the *box's*, and this member
deliberately does not restate the ceiling: a second allowlist here would be a
second thing to keep in sync with
:data:`sandbox.COMMITTED_IMPORTS_ALLOWLIST`, which is exactly the drift the
member's own ``imports_allowlist.json`` exists to prevent.  So
:meth:`SignalContract.adopt` takes an optional ``screen`` — the box's own
admission test as a callable source → decision — and when a caller supplies
one, a proposal the box would refuse is not adopted, with the box's own
sentence carried into the refusal.  Duck-typed and imported by nobody: the
law is handed a callable, reads ``admitted`` and ``detail`` off its answer,
and never learns the sandbox member's name.

**The declaration is not guidance.**  :meth:`SignalContract.declaration`
returns the ABI a proposal must conform to — the entrypoint, its parameters,
the return shape, and the *accessor surface* the window exposes (read through
:func:`contract.inspect_accessors`, so feature 10's no-widening guard is what
answers it).  It is contract, and deliberately not advice: §14.1 and PRD §9.9
are explicit that directional guidance distilled from history — "the paper's
Figure 5 found this consistently *underperformed*" — must not be injected into
the prompt, and feature 208 makes rejecting that injection its own feature.  A
declaration of what the box will invoke cannot over-constrain a search; a
paragraph about where to look can.  Keeping the first here and the second out
is the whole reason this method returns a mapping of facts rather than prose.

Stdlib only, and import-cheap: :mod:`enum`, :mod:`hashlib`, :mod:`typing` and
the member's own errors, so the factory's scan — which imports this package to
fire its ``@register`` — pays nothing for it.  ``contract`` is reached inside
the methods that need the ABI (see :func:`require_contract`), because the scan
imports one member at a time with that member's own ``src/`` on ``sys.path``
and a module-scope import would make this component's presence depend on scan
order.
"""

from __future__ import annotations

import enum
import hashlib
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, Any, Final

from .errors import AgentSourceError

if TYPE_CHECKING:  # pragma: no cover - typing only; the ABI is resolved lazily
    from contract import NodeAbiRecord, SignalSignature

__all__ = [
    "CONFORMS_CODE",
    "AdoptionReason",
    "SignalContract",
    "SourceAdoption",
    "require_contract",
    "signal_contract",
    "source_code_hash",
]

#: The token every conforming adoption's sentence carries — the feature's own
#: subject written as a word, so an operator grepping a campaign log for the
#: proposals that became nodes finds them by it.  Its mirror is the refusal,
#: which opens with its :class:`AdoptionReason` value instead; a refusal is a
#: different answer and should not read like an adoption with a footnote.
CONFORMS_CODE: str = "conforming_signal"


def source_code_hash(source: str) -> str:
    """The sha256 hexdigest of a signal source, as the tree's identity.

    §9.1's ``code_hash CHAR(64)``, filled the way every writer in this
    workspace fills it: ``sha256(source.encode("utf-8")).hexdigest()``, the
    evaluator's step 6 being the reference spelling and
    :func:`artifacts.source_code_hash` stating the same thing from the
    artifact side of the boundary.  This member is the third place a source
    is hashed — the moment it is *adopted*, before it is ever persisted — and
    the three must agree to the byte, because a tree row whose ``code_hash``
    disagrees with the text the sandbox ran is a node no replay reproduces.
    Three lines of stdlib restated with a pointer is cheaper here than a
    member dependency on the evaluator or the artifact store, and it is the
    same trade :func:`artifacts.source_code_hash` makes for its own copy.

    Validated as text first — a hash of something that is not a string is the
    identity of a ``node.code`` that will never exist, and returning one
    would let a caller persist a hash for a proposal it never adopted.
    """
    if not isinstance(source, str):
        raise AgentSourceError(
            f"a signal source's code hash must be taken over text, got "
            f"{type(source).__name__}; §9.1's code_hash identifies the exact "
            f"source the sandbox executed, and a value that is not source "
            f"has no such identity (feature 205)."
        )
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def require_contract():
    """Import and return :mod:`contract`, or raise a named, actionable error.

    Called from inside the methods that need the ABI rather than at module
    scope, for the reason :func:`contract._arrow.require_arrow` gives for
    pyarrow and :mod:`evaluator._sandbox` gives for ``contract`` itself: the
    factory's workspace scan imports this package to fire its ``@register``,
    and the scan puts *one* member's ``src/`` on ``sys.path`` at a time — so a
    module-scope ``import contract`` here would make this component's presence
    in the composed application depend on scan order.  Deferring the import
    keeps the member import-safe in the environments the workspace contract
    promises one will be (factory scan, test sandbox, replay path), while a
    caller that genuinely needs the ABI and cannot reach the contract member
    is told which wheel is missing rather than shown a bare ImportError.
    """
    try:
        import contract
    except ModuleNotFoundError as exc:  # pragma: no cover - declared dependency
        raise ModuleNotFoundError(
            "the signal-agent member enforces the signal contract the "
            "nullius-contract member declares, and that member is not "
            "importable in this environment; run `uv sync --all-packages` in "
            "the workspace root (or put packages/contract/src on sys.path) so "
            "the ABI this member checks against can be read"
        ) from exc
    return contract


class AdoptionReason(enum.StrEnum):
    """Why a proposal was adopted or refused — the audit vocabulary.

    A :class:`enum.StrEnum` whose *value* is the token every refusal's
    :attr:`SourceAdoption.detail` opens with, so the reason is greppable in a
    campaign log without a lookup table and a reader never has to match a
    sentence to a category by eye.  The five are split by *repair*, not by
    which check happened to fail: two proposals that both fail to conform but
    one of which returned a dict and the other a blank string are two
    different prompts to the retrying agent.
    """

    #: Adopted: the source compiles, declares the entrypoint with the declared
    #: parameters, and (when a screen was supplied) is admitted by the box.
    CONFORMS = "conforms"

    #: Refused: the proposal is not source text at all — a mapping, a list, a
    #: ``None``, or any non-string the agent may have handed back instead of
    #: code.  Its own reason rather than a spelling of the blank case because
    #: the repair is at the *call shape*: the agent was asked for a signal
    #: function and answered with something that is not one.
    NOT_SOURCE = "not-source"

    #: Refused: the proposal is a string with nothing in it.  Distinct from
    #: :attr:`NOT_SOURCE` because the repair is different — an empty response
    #: is a truncation, a refusal to answer or a stream that ended early, and
    #: an operator looking for a type bug would be looking in the wrong place.
    BLANK_SOURCE = "blank-source"

    #: Refused: the text is source and it is not *this* source — it does not
    #: compile, or it compiles without a ``signal`` entrypoint, or the
    #: entrypoint's parameters are not the declared window-then-seed. This is
    #: the reason feature 205's own word *conforming* is about, and the one
    #: that carries :attr:`SourceAdoption.problems` — the validator's own
    #: sentences — for a retry prompt to quote.
    NOT_CONFORMING = "not-conforming"

    #: Refused: the source conforms to the signal contract and the *box*
    #: refused it — an import outside the sandbox's configured allowlist, say
    #: (feature 167).  The reason is its own because the two authorities are
    #: different: the contract says what the sandbox will *invoke*, the box
    #: says what it will *admit*, and a caller told only "not conforming"
    #: would go looking for a signature bug in a proposal whose signature is
    #: correct.
    REFUSED_BY_BOX = "refused-by-box"


class SourceAdoption:
    """One proposal's verdict: adopted or not, why, and in what words.

    ``adopted`` is the one field a caller must check, and it is *computed*
    from the reason rather than set by a constant — the same "computed, never
    assumed" stance :class:`sandbox.SeedDecision` and
    :class:`sandbox.isolation.RunDecision` take for their own answers.  The
    object carries everything the four callers downstream need and nothing
    else:

    * :attr:`source` — the exact text the sandbox will execute, ``None`` for
      every refusal, so a caller that has checked ``adopted`` reads the text
      rather than a sentinel;
    * :attr:`code_hash` — §9.1's ``code_hash CHAR(64)``, computed once at
      construction from that same text, ``None`` for every refusal.  Carried
      rather than left to the caller because the hash and the text are two
      statements about one node, and a caller that recomputed one of them
      later is exactly the pair that can drift;
    * :attr:`problems` — the contract validator's own sentences, in its own
      order, empty when the proposal conforms.  Feature 206 reads every prior
      proposal in full and feature 209 decides whether to retry, and both of
      those need *what was wrong* rather than a boolean;
    * :attr:`detail` — one operator-facing paragraph, the sentence a campaign
      log records.

    **Its constructor refuses nothing.**  A caller holding a refusal is the
    caller that most needs one, and it cannot be told about an object it was
    never allowed to build — the discipline
    :class:`sandbox.seed.SandboxInvocation` states for its own constructor.
    ``source`` is taken as given (including ``None``), and the refusals live
    at :meth:`require`.
    """

    __slots__ = (
        "adopted",
        "code_hash",
        "detail",
        "problems",
        "reason",
        "source",
    )

    def __init__(
        self,
        *,
        reason: AdoptionReason,
        detail: str,
        source: str | None = None,
        problems: Iterable[str] = (),
    ) -> None:
        self.reason = reason
        self.detail = detail
        self.problems = tuple(problems)
        self.adopted = reason is AdoptionReason.CONFORMS
        self.source = source if self.adopted else None
        # The hash is taken here, once, from the text that was adopted: a
        # caller that took it later would be hashing "the source I think I
        # adopted", and the whole point of carrying it beside the source is
        # that the two cannot come apart (feature 15's pair).
        self.code_hash = source_code_hash(self.source) if self.adopted else None

    def require(self) -> str:
        """Return the adopted source, or raise :class:`AgentSourceError`.

        The bridge between the law's returned answer and the exception a
        caller wants on its last line before persisting a proposal: a
        conforming adoption returns the text §5.2's ``node.code`` will carry,
        so a caller can write ``source = law.adopt(text).require()`` and have
        feature 205 enforced there rather than remembered.  A refusal raises
        with this adoption's own sentence, so the retry prompt and the log
        line say the same thing.
        """
        if not self.adopted:
            raise AgentSourceError(self.detail)
        assert self.source is not None  # adopted implies a source, by construction
        return self.source

    def abi_record(self) -> NodeAbiRecord:
        """The pair a stored node persists: the code hash beside its ABI stamp.

        Feature 15's ``node_abi_record`` — the ``contract_version`` and the
        ``code_hash`` — built from *this* adoption, so the stamp describes the
        ABI the source was checked against rather than whichever ABI happens
        to be running when the row is finally written.  A refusal has no code
        hash and therefore no ABI record, so calling this on one raises the
        same :class:`AgentSourceError` :meth:`require` does: the pair is the
        identity of a node, and a refused proposal is not one.
        """
        if not self.adopted:
            raise AgentSourceError(self.detail)
        contract = require_contract()
        return contract.node_abi_record(code_hash=self.code_hash)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"SourceAdoption(reason={self.reason.value!r}, "
            f"code_hash={self.code_hash!r}, problems={len(self.problems)})"
        )


# -- CONTRACT-1: the declaration made usable, not merely named ---------------
#
# bug_spec_authoring_contract.xml's bug 1: a campaign's authored roots called
# ``getattr(ctx, "bars")`` and guessed at it, because :meth:`SignalContract.
# declaration` named the accessor surface without its signatures, its units or
# the schema the sealed snapshot actually carries.  The four helpers below
# build the additive detail declaration() now attaches; each reads its facts
# off the contract member (or the sandbox child's own ceiling) rather than
# restating them, on the same grounds :func:`contract.inspect_accessors`
# already gives the accessor *names*.


def _signature_text(name: str, method: Any) -> str:
    """``name(params...) -> polars.DataFrame``, read off the live method.

    Built from :func:`inspect.signature` rather than typed by hand, so a
    later feature that widens an accessor's parameters changes this string
    automatically.  Annotations are dropped from the rendering: every
    accessor module uses ``from __future__ import annotations``, so a raw
    ``str(parameter)`` would quote each annotation as a string literal
    (``"freq: 'str'"``) instead of reading as the call an agent should write.
    """
    import inspect

    parts: list[str] = []
    for param in inspect.signature(method).parameters.values():
        if param.name == "self":
            continue
        if param.default is inspect.Parameter.empty:
            parts.append(param.name)
        else:
            parts.append(f"{param.name}={param.default!r}")
    return f"{name}({', '.join(parts)}) -> polars.DataFrame"


def _accessors_detail(contract: Any) -> dict[str, dict[str, Any]]:
    """Per-accessor signature, parameter units and frame schema.

    Covers the five data accessors the symptom names — ``bars``, ``trades``,
    ``bookfeat``, ``borrow``, ``feature`` — never ``frames``/``t``/``universe``/
    ``to_arrow``, which carry no call shape an authored signal needs guessing
    at.  Each entry's ``signature`` comes from :func:`_signature_text` and its
    ``returns_columns`` from that accessor's own ``*_REQUIRED_COLUMNS``
    constant (:mod:`contract.bars`, ``.trades``, ``.bookfeat``, ``.borrow``) —
    read, not retyped — so a widened required-column set shows up here without
    a second edit.  ``feature`` carries no such constant (§9.1: the schema is
    whatever the named, versioned feature stored), so it states that fact
    instead of a column list. The remaining prose — units, and the sealed
    snapshot's venue-string convention for OHLCV fields — has no machine
    constant to read, because it is not type-checked anywhere in the contract;
    it is the exact gap the symptom names (the momentum root that guessed
    ``close``'s dtype), so it is stated here in words.
    """
    window = contract.MarketWindow
    return {
        "bars": {
            "signature": _signature_text("bars", window.bars),
            "freq_values": contract.BARS_FREQUENCIES,
            "lookback_unit": (
                "bars (rows) of the requested freq, trailing; None reads "
                "every row the window carries"
            ),
            "returns_columns": contract.BARS_REQUIRED_COLUMNS,
            "returns_notes": (
                "extra OHLCV columns pass through verbatim; in the sealed "
                "snapshot open_time is a UTC timestamp while close and "
                "volume arrive as venue-spelled strings (e.g. \"61234.50\") "
                "-- cast close to Float64 before arithmetic"
            ),
        },
        "trades": {
            "signature": _signature_text("trades", window.trades),
            "lookback_unit": (
                "seconds before ctx.t, inclusive both ends -- not a row count"
            ),
            "returns_columns": contract.TRADES_REQUIRED_COLUMNS,
            "returns_notes": (
                "event_time is a UTC timestamp; other tape columns are "
                "venue-spelled"
            ),
        },
        "bookfeat": {
            "signature": _signature_text("bookfeat", window.bookfeat),
            "lookback_unit": "rows (1-second buckets), trailing; None reads every row",
            "returns_columns": contract.BOOKFEAT_REQUIRED_COLUMNS,
            "returns_notes": (
                "name is free-form, addressing bookfeat:<name>; derived "
                "fields are fixed-point strings"
            ),
        },
        "borrow": {
            "signature": _signature_text("borrow", window.borrow),
            "lookback_unit": "rows, trailing; None reads every row",
            "returns_columns": contract.BORROW_REQUIRED_COLUMNS,
            "returns_notes": "borrow_rate and other fields are venue-spelled strings",
        },
        "feature": {
            "signature": _signature_text("feature", window.feature),
            "lookback_unit": "rows, trailing; None reads every row",
            "returns_notes": (
                "schema is whatever the named, versioned feature stored; a "
                "name/version this window does not carry returns an empty, "
                "columnless frame"
            ),
        },
    }


#: ctx.universe's shape and the alignment it demands of a signal's return --
#: missing from the prompt per the symptom, though :meth:`SignalContract.
#: declaration`'s existing ``returns`` field already states the alignment
#: half; this key adds the type half it omitted.
_UNIVERSE_NOTE: Final[str] = (
    "ctx.universe is a read-only tuple[str, ...] of symbol strings, in a "
    "fixed order (the roster tradable as of ctx.t); the returned Series must "
    "be positionally aligned to it -- index i's score is universe[i]'s score"
)

#: A short, correct example over the one stream the operator's own snapshot
#: actually carries (bars at 1d) -- casts the venue-string close to Float64
#: and returns a Float64 Series aligned to ctx.universe, exactly the two
#: steps the symptom's momentum root skipped.
EXAMPLE_SIGNAL_SOURCE: Final[str] = '''def signal(ctx, seed):
    import polars as pl

    bars = ctx.bars("1d", lookback=20).with_columns(
        pl.col("close").cast(pl.Float64)
    )
    scores: dict[str, float] = {}
    for symbol in ctx.universe:
        rows = bars.filter(pl.col("symbol") == symbol).sort("open_time")
        if rows.height < 2 or rows["close"][0] == 0.0:
            scores[symbol] = 0.0
        else:
            scores[symbol] = rows["close"][-1] / rows["close"][0] - 1.0
    return pl.Series([scores[s] for s in ctx.universe], dtype=pl.Float64)
'''


def _agent_imports_allowlist() -> tuple[str, ...]:
    """The sandbox child's own import ceiling, read live rather than restated.

    :data:`orchestrator._sandbox_child.AGENT_IMPORTS_ALLOWLIST` is what the
    gVisor/bubblewrap child actually enforces against an authored signal's
    top-level imports -- not :data:`sandbox.COMMITTED_IMPORTS_ALLOWLIST`'s
    committed JSON document, which is the separate host-side admission test
    bug 2 of this same spec fixes, and which (at the time of this fix) still
    over-admits ``numpy``.  Reading the child's own ceiling live means a later
    change to the runtime's import surface updates what the model is told
    with no second edit here.

    Deferred and guarded on the same grounds :func:`require_contract` defers
    ``contract``: a module-scope import would make this component's presence
    depend on workspace scan order, and ``orchestrator`` is not a declared
    dependency of this member (it is the reverse: orchestrator depends on
    signal-agent), so the import is reached for only when this fact is asked
    for, never at import time.
    """
    try:
        from orchestrator._sandbox_child import AGENT_IMPORTS_ALLOWLIST
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "the authoring declaration names the sandbox child's own import "
            "ceiling, and the orchestrator member (its _sandbox_child "
            "bootstrap) is not importable in this environment; run `uv sync "
            "--all-packages` in the workspace root (or put "
            "packages/orchestrator/src on sys.path) so the ceiling this "
            "declaration reports can be read"
        ) from exc
    return tuple(sorted(AGENT_IMPORTS_ALLOWLIST))


def _parquet_interval(path: Any) -> str | None:
    """One Parquet file's ``interval`` column value, or ``None``.

    Best-effort: a file that cannot be opened, carries no ``interval``
    column, or carries none at all answers ``None`` rather than raising --
    this is a sample read for a prompt-building fact, not a correctness gate
    any accessor enforces. pyarrow is reached for lazily, since a caller that
    never configures a ``snapshot`` for :meth:`SignalContract.declaration`
    must not pay for it.
    """
    try:
        import pyarrow.parquet as pq
    except ModuleNotFoundError:
        return None
    try:
        schema = pq.read_schema(str(path))
        if "interval" not in schema.names:
            return None
        table = pq.read_table(str(path), columns=["interval"])
    except Exception:  # noqa: BLE001 - a foreign file's bytes, read best-effort
        return None
    if table.num_rows == 0:
        return None
    value = table.column("interval")[0].as_py()
    return value if isinstance(value, str) and value else None


def _stream_frequencies(
    stream: str, partitions: Any, dates: Any, select: Any
) -> tuple[str, ...]:
    """The distinct ``interval`` values one symbol's files carry under ``stream``.

    Sampled over the *first* partitioned symbol's whole history rather than
    every symbol: every producer in this workspace writes one interval per
    partition tree (:mod:`nullius_ingest.klines`: "a batch is one interval"),
    so one symbol's files already show every cadence the stream holds, at a
    fraction of the file-open cost a full-universe scan would pay. A stream
    whose files carry no ``interval`` column (trades, bookfeat, borrow -- none
    of the three is frequency-partitioned) answers with an empty tuple: present,
    with no cadence to report.
    """
    symbols = partitions(stream)
    if not symbols:
        return ()
    symbol = symbols[0]
    frequencies: set[str] = set()
    for date in dates(stream, symbol):
        for path in select(stream, symbol, date):
            freq = _parquet_interval(path)
            if freq is not None:
                frequencies.add(freq)
    if not frequencies and stream == _EVALUATOR_BARS_STREAM:
        # Date-partitioned bars with no ``interval`` column -- the layout
        # nullius_ingest.bars_backfill seals and the only one the evaluator
        # reads -- are materialized by orchestrator._evaluate as the single
        # ``bars:1d`` frame, so 1d is the one frequency a signal is served.
        # Reporting () here told the model "bars exist" without saying which
        # frequency, and it asked for 1h (smoke campaign 360f6f00).
        return (_EVALUATOR_BARS_FREQUENCY,)
    return tuple(sorted(frequencies))


#: The stream orchestrator._evaluate materializes from date-partitioned bars,
#: and the one frequency it serves it at (its ``bars:1d`` frame).
_EVALUATOR_BARS_STREAM = "bars"
_EVALUATOR_BARS_FREQUENCY = "1d"


def _available_streams(snapshot: Any) -> dict[str, tuple[str, ...]] | None:
    """``{stream: (frequencies present,)}`` off a sealed mount, or ``None``.

    ``None`` -- and the key is absent from :meth:`SignalContract.declaration`'s
    mapping entirely -- exactly when no ``snapshot`` was configured for the
    call: the symptom is that a model was told accessor names with no word on
    which streams the *evaluation* context actually serves, and a declaration
    that invented an answer with no context configured would trade one
    guess for another.

    ``snapshot`` is accepted structurally -- anything exposing ``files()``,
    ``partitions(stream)``, ``dates(stream, symbol)`` and
    ``select(stream, symbol, date)`` is a sealed snapshot mount to this
    function, the same surface :class:`snapshot.SnapshotMount` and
    :func:`evaluator._window._mount_queries` already share -- so this member
    adds no dependency on ``snapshot`` to read one.  Stream names are the
    first path segment of every file :meth:`files` reports (never a fixed
    guess at which stream kinds exist), so a producer this workspace has not
    written yet (trades, bookfeat, borrow) is reported the moment something
    seals one.
    """
    if snapshot is None:
        return None
    files = getattr(snapshot, "files", None)
    partitions = getattr(snapshot, "partitions", None)
    dates = getattr(snapshot, "dates", None)
    select = getattr(snapshot, "select", None)
    if not all(callable(fn) for fn in (files, partitions, dates, select)):
        raise TypeError(
            "declaration()'s snapshot must be a sealed snapshot mount "
            "exposing files(), partitions(stream), dates(stream, symbol) and "
            "select(stream, symbol, date) -- snapshot.SnapshotService."
            "mount(...)'s own shape -- so available_streams names only what "
            "the evaluation context actually holds, never a guess"
        )
    stream_names = sorted({path.split("/", 1)[0] for path in files() if path})
    return {
        stream: _stream_frequencies(stream, partitions, dates, select)
        for stream in stream_names
    }


class SignalContract:
    """Feature 205's law, as the value a composed application carries.

    A facade over :mod:`contract.signal` and this module — the same shape
    :class:`sandbox.SandboxSeed` gives feature 165,
    :class:`sandbox.SandboxTransfer` gives feature 166 and
    :class:`artifacts.ArtifactStore` gives its own category — so a caller
    holding the composed component can ask feature 205's question, *did the
    agent write a signal function conforming to the declared contract?*,
    without importing either member's submodules by name.

    **It carries nothing.**  No proposal, no source, no node, no campaign, no
    store: an adoption is a fact about one piece of text, and a component
    shared across a campaign that carried one would let two nodes' verdicts
    be read through each other — the property
    :class:`sandbox.transfer.SandboxTransfer` states for its channel and
    :class:`sandbox.seed.SandboxSeed` restates for its seed.

    **Every verb is one call into the law below it** — the validator lives in
    :mod:`contract.signal`, where the ABI it checks against is declared, and
    the box's screen is the box's.  What this class adds is discoverability
    (the factory's scan composes it), one duck-checkable seam for the
    category's remaining features, and the *declaration* — the shape an agent
    is asked to write against, assembled from the contract rather than
    restated here.
    """

    __slots__ = ()

    def signature(self) -> SignalSignature:
        """The declared signal signature — the ABI's own value object.

        Returns :class:`contract.SignalSignature` itself rather than a copy or
        a local spelling of it: two callers who mean the same entrypoint must
        be holding the same value, or one of them is holding a stale idea of
        it.  Feature 11 owns the shape; this member owns only the asking.
        """
        return require_contract().describe_signal_signature()

    def validate(self, source: object) -> tuple[str, ...]:
        """The contract's own problems with ``source``, in its own order.

        The thin read of :func:`contract.validate_signal_signature`, exposed
        because a caller auditing a *history* (feature 206 reads every prior
        proposal in full) wants the problems without a verdict attached.
        Nothing is raised for a non-conforming source: the returned tuple is
        empty exactly when the source declares the entrypoint the sandbox
        invokes.  A source that is not text at all is the one exception —
        there is nothing for the validator to compile, so a single problem
        naming the type is returned rather than a guess at what was meant.
        """
        contract = require_contract()
        if not isinstance(source, str):
            problem = (
                f"a signal source must be text, got {type(source).__name__}; "
                "the sandbox compiles what the agent wrote (feature 205, "
                "§5.2), so a proposal that is not source has nothing to "
                "compile"
            )
            return (problem,)
        return tuple(contract.validate_signal_signature(source))

    def adopt(
        self,
        source: object,
        *,
        screen: Callable[[str], Any] | None = None,
    ) -> SourceAdoption:
        """Judge one proposal: adopt it only as a conforming signal source.

        The feature's verb.  In order, and each step's own reason:

        1. **it is text** — a non-string is refused with
           :attr:`AdoptionReason.NOT_SOURCE`;
        2. **it is not blank** — an empty or whitespace-only string is refused
           with :attr:`AdoptionReason.BLANK_SOURCE`, before the validator is
           consulted, because a blank proposal has no entrypoint to be missing
           and a compile error about line 1 of nothing helps nobody;
        3. **it conforms** — :meth:`validate` runs, and any problem refuses
           with :attr:`AdoptionReason.NOT_CONFORMING`, carrying the validator's
           sentences in :attr:`SourceAdoption.problems`;
        4. **the box admits it**, when a ``screen`` was supplied — the box's
           own decision (duck-read: ``admitted`` and ``detail``) refuses with
           :attr:`AdoptionReason.REFUSED_BY_BOX`.  The box's sentence is
           carried verbatim rather than translated: feature 167's refusal is
           the box's, and a member that re-worded it would be a second source
           of truth about why a submission was rejected.

        The adopted text is returned **unmodified**.  Adoption is a judgement
        about the agent's source, never an edit of it: the ``code_hash``
        persisted beside the node is the hash of exactly what the sandbox
        executes, so a member that stripped a trailing newline here would
        produce a tree row whose identity disagrees with the bytes the box
        ran.
        """
        if not isinstance(source, str):
            return SourceAdoption(
                reason=AdoptionReason.NOT_SOURCE,
                detail=(
                    f"{AdoptionReason.NOT_SOURCE.value}: the agent's proposal "
                    f"is {type(source).__name__}, not source text. Feature "
                    f"205 asks the agent for a signal function and §5.2's box "
                    f"compiles what it wrote, so a proposal that is not text "
                    f"is not a candidate for adoption — the retry wants the "
                    f"agent to emit code, not to emit a better-typed "
                    f"something else (feature 205)."
                ),
            )

        if not source.strip():
            return SourceAdoption(
                reason=AdoptionReason.BLANK_SOURCE,
                detail=(
                    f"{AdoptionReason.BLANK_SOURCE.value}: the agent's proposal "
                    f"is a string of {len(source)} character(s) containing no "
                    f"source. An empty response is a truncation, an unseated "
                    f"completion or a stream that ended early, and none of "
                    f"those is a signal function — refused before the "
                    f"validator is consulted, because a blank submission has "
                    f"no entrypoint to be missing (feature 205)."
                ),
            )

        problems = self.validate(source)
        if problems:
            listed = "; ".join(problems)
            return SourceAdoption(
                reason=AdoptionReason.NOT_CONFORMING,
                detail=(
                    f"{AdoptionReason.NOT_CONFORMING.value}: the agent's "
                    f"proposal does not declare the signal contract the "
                    f"system will invoke — {listed}. The contract is §5.1's "
                    f"one entrypoint, "
                    f"{_invocation_text(self.signature())}, and a proposal "
                    f"the sandbox cannot call is refused here rather than "
                    f"persisted as a node whose code_hash identifies source "
                    f"no run could reproduce (features 205, 11, 15)."
                ),
                problems=problems,
            )

        if screen is not None:
            refusal = _screen_refusal(screen, source)
            if refusal is not None:
                return SourceAdoption(
                    reason=AdoptionReason.REFUSED_BY_BOX,
                    detail=(
                        f"{AdoptionReason.REFUSED_BY_BOX.value}: the proposal "
                        f"declares the signal contract correctly and the "
                        f"sandbox refused it — {refusal}. The two authorities "
                        f"are different: the contract says what the box will "
                        f"*invoke* and the box says what it will *admit*, so a "
                        f"signature-correct proposal can still be one the run "
                        f"never executes (features 205, 167, §5.2)."
                    ),
                )

        return SourceAdoption(
            reason=AdoptionReason.CONFORMS,
            source=source,
            detail=(
                f"{CONFORMS_CODE}: the agent's proposal declares "
                f"{_invocation_text(self.signature())} and is adopted as the "
                f"node's source — §5.2's ``code=node.code``, the exact text "
                f"the sandbox executes, whose sha256 is the code_hash §9.1 "
                f"stores beside the contract_version (features 205, 11, 15)."
            ),
        )

    def declaration(self, *, snapshot: Any | None = None) -> dict[str, Any]:
        """The contract as a plain mapping — what an agent is asked to write.

        Assembled from the contract rather than restated: the entrypoint and
        its parameters from :meth:`signature`, the ABI reference and version
        from the composed contract component, and the window's *accessor
        surface* from :func:`contract.inspect_accessors` — the same call
        feature 10's no-widening guard runs, so the surface an agent is told
        it may read is the surface the class actually exposes, and a later
        feature that widened it would fail here rather than in a prompt.

        A mapping, and deliberately facts only.  PRD C3 and §14.1 forbid
        injecting directional guidance distilled from history into the
        authoring prompt — *"the paper's Figure 5 found this consistently
        underperformed"* — and feature 208 is the feature that refuses it.  A
        declaration of the ABI the box will invoke cannot over-constrain a
        search space; prose about where to look can.  Returning a mapping is
        how this method stays on the right side of that line: there is no
        field here for a suggested mechanism, a theme hint, or a summary of
        what has already been tried.

        **CONTRACT-1's additive detail.**  Every key above is unchanged from
        before that bug's fix; what follows is what it added, because naming
        an accessor's surface is not the same as making it usable (an
        authored root that calls ``getattr(ctx, "bars")`` with no signature,
        no schema and no known stream to read from can only guess):

        * ``accessors_detail`` — :func:`_accessors_detail`'s per-accessor
          signature, parameter units and frame schema, for the five data
          accessors (``bars``, ``trades``, ``bookfeat``, ``borrow``,
          ``feature``).
        * ``universe`` — :data:`_UNIVERSE_NOTE`, the type ``returns`` above
          assumes but never states: ``ctx.universe`` is a ``tuple[str, ...]``.
        * ``allowed_imports`` — :func:`_agent_imports_allowlist`, the sandbox
          child's own import ceiling.
        * ``example_signal`` — :data:`EXAMPLE_SIGNAL_SOURCE`, one short,
          correct signal over ``bars("1d", lookback)``.
        * ``available_streams`` — :func:`_available_streams` over
          ``snapshot``, present only when a caller configures one (``None``
          by default, so every existing call site — none of which passes
          ``snapshot`` — is unaffected); absent from the mapping entirely
          when it is not.
        """
        contract = require_contract()
        sig = contract.describe_signal_signature()
        declared: dict[str, Any] = {
            "entrypoint": sig.entrypoint,
            "window_arg": sig.window_arg,
            "seed_arg": sig.seed_arg,
            "signature": _invocation_text(sig),
            "returns": (
                "polars.Series of finite floats, one value per symbol of "
                "ctx.universe, positionally aligned: the i-th value is the "
                "score for the i-th symbol (feature 11)"
            ),
            "market_window": contract.MARKET_WINDOW_ABI,
            "contract_version": contract.CONTRACT_VERSION,
            "accessors": tuple(contract.inspect_accessors()),
            "purity": (
                "the window is the only argument that carries data and the "
                "seed the only one that carries randomness: no clock, no "
                "filesystem, no network, no global state (§5.1, §12)"
            ),
            "accessors_detail": _accessors_detail(contract),
            "universe": _UNIVERSE_NOTE,
            "allowed_imports": _agent_imports_allowlist(),
            "example_signal": EXAMPLE_SIGNAL_SOURCE,
        }
        streams = _available_streams(snapshot)
        if streams is not None:
            declared["available_streams"] = streams
        return declared


def _invocation_text(sig: SignalSignature) -> str:
    """The call the sandbox makes, spelled from the signature it will make it with.

    ``signal(ctx, seed)`` — read off the declared signature rather than
    written as a literal here, so a message that quotes the contract quotes
    the contract and not this module's memory of it.
    """
    return f"{sig.entrypoint}({sig.window_arg}, {sig.seed_arg})"


def _screen_refusal(screen: Callable[[str], Any], source: str) -> str | None:
    """The box's refusal of ``source``, or ``None`` when the box admits it.

    Reads the decision duck-typed — ``admitted`` and ``detail`` — so this
    member never imports the sandbox and never *raises the box's own error
    type*: feature 167 refuses a bad import with
    ``sandbox.DisallowedImportError``, and a member that let that escape would
    hand a caller of *this* law an exception its ``except SignalAgentError``
    clause does not catch.  So the box's sentence travels as a *value* into
    the adoption's detail, and the error a caller eventually catches is this
    member's, on the last line before it persists anything.

    A screen that cannot answer — raises, or returns something without an
    ``admitted`` attribute — is a caller's wiring error rather than a verdict
    about the proposal, so it is reported as such instead of being silently
    read as an admission.
    """
    try:
        decision = screen(source)
    except Exception as exc:
        raise AgentSourceError(
            f"the box screen handed to adopt() raised "
            f"{type(exc).__name__}: {exc}. The screen is the sandbox's own "
            f"admission test (feature 167), and a screen that cannot answer "
            f"has not admitted anything — reading its failure as an admission "
            f"would adopt a proposal on the strength of an exception "
            f"(feature 205)."
        ) from exc

    admitted = getattr(decision, "admitted", None)
    if not isinstance(admitted, bool):
        raise AgentSourceError(
            f"the box screen handed to adopt() answered with "
            f"{type(decision).__name__}, which carries no boolean 'admitted' "
            f"field. The screen is the sandbox's admission decision "
            f"(feature 167) and its answer is what allows an adoption; a "
            f"value this law cannot read is refused rather than treated as an "
            f"admission (feature 205)."
        )
    if admitted:
        return None
    return str(getattr(decision, "detail", "") or "no reason given")


def signal_contract() -> SignalContract:
    """The law, for a caller that wants it directly.

    Not a component — the ``@register("signal-agent")`` builder in this
    member's ``__init__`` is, and this is the same call minus the
    composition.  The member's own tests and any operator script reach here.
    """
    return SignalContract()
