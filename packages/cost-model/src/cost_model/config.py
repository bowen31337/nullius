"""Feature 59's configuration layer: the YAML cost model, loaded and resolved.

app_spec.xml, "Cost Model & Fill Simulation", feature 59: *System persists
the resolved cost model version string with its venue name after loading
the YAML configuration.*  docs/nullius-tech-architecture.md §6.2 fixes the
document and the two values this module is responsible for:

.. code-block:: yaml

    cost_model:
      version: "2026.09.1"
      venue: binance_spot
      fees:
        taker_bps: 10.0
        ...

Four words in the feature's sentence are four separable claims, and this
module owns the first three — *loading*, *the YAML configuration*, and
*resolved* — while :mod:`cost_model.store` and
:mod:`cost_model.service` own the fourth.

**The document is YAML, and it is parsed as YAML.**  §2 puts the cost model
in the Z0 trust zone (``docs/nullius-tech-architecture.md``: *"The
evaluator, cost model, and data snapshots live in a read-only trust zone
that LLM-authored code has no write credential for"*), and §6.2 writes it
as YAML.  A member that must read a signed artifact parses it with a real
YAML parser rather than a hand-rolled subset of one: a subset quietly
means something different on the day the file grows a nested list, a
multi-line string or an anchor, and "quietly different" is the one failure
mode a fee schedule may not have.  The parser is therefore
:func:`yaml.safe_load` — *safe* on purpose, never the arbitrary-object
constructor.  The document is operator-writable in the environments this
member runs in, so constructing Python objects named by its content is a
deserialization hazard with no upside: a fee schedule is scalars, lists
and mappings, and that is all ``safe_load`` will build.

**Both spellings of the document resolve.**  §6.2 nests the model under a
``cost_model`` key; an operator composing a larger settings file may
instead hand this member a document that *is* the model.  Rather than
guess, the loader takes the ``cost_model`` block when the document carries
one and otherwise reads the document itself as the model, and the error it
raises when neither spelling yields a version and a venue names both
shapes.  Precedence is stated rather than implied: a document carrying a
``cost_model`` key is read through that key, so a larger file can hold
other sections beside the model without any of them being mistaken for it.

**"Resolved" is a value, not a string that happened to load.**  The two
things feature 59 persists are :attr:`~CostModelConfig.version` and
:attr:`~CostModelConfig.venue`, and the loader will not hand back a config
that lacks either: a missing key, a blank string, a number, a list — each
is refused by name, with the offending value in the message.  The version
in particular must be a *string*, and a bare numeric version is refused
with a message telling the author to quote it, because YAML renders
``1.0`` as a float and ``str(1.0)`` is not a spelling any human wrote —
the value feature 60 hashes and a score names must be the text the
document carries, not a re-render of it.

The dependency on PyYAML is real but *deferred*: :func:`require_yaml`
imports it on first use and raises a :class:`ModuleNotFoundError` naming
the fix when it is absent, so the factory's workspace scan — which imports
this package to fire its ``@register`` decorator — does not require PyYAML
to be installed.  The same seam, and the same reasoning, as
``feature_store.parquet.require_arrow``.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Optional, Union

from .errors import CostModelConfigError

__all__ = [
    "COST_MODEL_KEY",
    "COST_MODEL_PATH_ENV",
    "DEFAULT_COST_MODEL_PATH",
    "CostModelConfig",
    "load_cost_model",
    "read_cost_model_document",
    "require_yaml",
]

#: The environment variable naming the YAML cost model document to load.
#:
#: Spelled with the member prefix the universe component established
#: (``NULLIUS_UNIVERSE_*``), so the workspace's environment overrides are
#: one family rather than a pile of unrelated names.  Unset, the loader
#: falls back to :data:`DEFAULT_COST_MODEL_PATH`; the builder in
#: :mod:`cost_model.service` is the caller that reads it.
COST_MODEL_PATH_ENV = "NULLIUS_COST_MODEL_PATH"

#: The document's own key for the model, per docs/nullius-tech-architecture.md §6.2.
COST_MODEL_KEY = "cost_model"

#: The document this member falls back to when no path is configured.
#:
#: Shipped inside the package (``src/cost_model/cost_model.yaml``) rather
#: than at the repository root, so it travels with the installed member and
#: a composed application resolves a cost model in any environment without a
#: deployment step.  It carries §6.2's own version and venue — the document
#: the architecture writes down — so the defaults encode the spec, not
#: taste.  A real deployment points :data:`COST_MODEL_PATH_ENV` at the
#: signed Z0 artifact; this default is what the member reads until it does.
DEFAULT_COST_MODEL_PATH = Path(__file__).resolve().parent / "cost_model.yaml"

# The model's two required components, in the order error messages name them.
_REQUIRED_KEYS = ("version", "venue")


def require_yaml():
    """Import and return the ``PyYAML`` module, or raise a named error.

    The one place in this package that reaches for YAML (see the module
    docstring for why the import is deferred).  Imported lazily on every
    call rather than cached in a module global: the cost after the first
    import is a ``sys.modules`` lookup, and a cache would be a lie in the
    one environment where it matters — a test that installs, removes or
    monkeypatches PyYAML mid-process.

    A missing PyYAML raises :class:`ModuleNotFoundError` naming the fix,
    following the shape of ``feature_store.parquet.require_arrow`` and
    ``contract._arrow.require_arrow`` — the seam lives in the member that
    declares the dependency.  A missing *parser* is an environment problem,
    not a malformed document, so it is deliberately not a
    :class:`~cost_model.errors.CostModelConfigError`.
    """
    try:
        import yaml
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on the env
        raise ModuleNotFoundError(
            "the cost model reads the YAML configuration of "
            "docs/nullius-tech-architecture.md §6.2, which needs PyYAML; "
            "install it (`uv sync` installs the dependency this member "
            "declares as pyyaml)"
        ) from exc
    return yaml


@dataclass(frozen=True)
class CostModelConfig:
    """The resolved cost model identity: a version string and a venue name.

    The two values feature 59 names, and only those two.  §6.2's document
    carries more — the fee basis points, the fill model, the latency
    distribution's source — and those belong to the features that consume
    them (61 applies the fees, 63-66 the fill model, 67 the latency
    distribution).  This value is what *loading* the configuration
    resolves: which schedule this is (:attr:`version`) and which venue it
    prices (:attr:`venue`).  Everything downstream is keyed off the pair,
    so a config that cannot name both is not a cost model at all and is
    refused at construction.

    Attributes:
        version: The version string the document carries, verbatim apart
            from surrounding whitespace.  A *string*: see the module
            docstring for why a bare numeric version is refused rather
            than re-rendered.
        venue: The venue the schedule prices, as the document spells it.
        source: Where the configuration was loaded from — the path for a
            file, else a short description of the origin.  Provenance only:
            it is recorded beside the resolved pair and takes no part in
            their identity, so the same document loaded from two
            deployments is the same cost model.

    The dataclass is frozen and validates in ``__post_init__``, so the
    invariant holds for every instance — one the loader built and one a
    test or a tool built by hand alike.
    """

    version: str
    venue: str
    source: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "version", _validated_component(self.version, "version"))
        object.__setattr__(self, "venue", _validated_component(self.venue, "venue"))
        if self.source is not None and not isinstance(self.source, str):
            raise CostModelConfigError(
                f"source must be a string when given, got "
                f"{type(self.source).__name__}"
            )

    @property
    def reference(self) -> str:
        """The resolved pair as one string: ``"<venue>/<version>"``.

        Feature 59 persists the version *with* its venue — the two are
        resolved together and are meaningless apart, since ``"2026.09.1"``
        alone does not say whose fee schedule it is.  This is that pairing
        spelled once, so a log line, an error message and a persisted
        record cannot each invent their own order for the same fact.
        """
        return f"{self.venue}/{self.version}"

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.reference


def _validated_component(value: object, key: str) -> str:
    """Return ``value`` as the resolved ``key``, or refuse it by name.

    The single validator for both components of the resolved pair, so
    ``version`` and ``venue`` cannot drift into different rules.  A
    non-string is refused with the fix in the message (quoting the value);
    a blank string is refused as absent, because ``version: ""`` names no
    version and a whitespace-only venue is a typo, not a venue.
    """
    if not isinstance(value, str):
        raise CostModelConfigError(
            f"the cost model's {key} must be a string, got "
            f"{type(value).__name__} ({value!r}); quote it in the YAML so the "
            f"{key} is read as the text the document carries"
        )
    text = value.strip()
    if not text:
        raise CostModelConfigError(
            f"the cost model's {key} is blank; a resolved cost model names a "
            f"non-empty {key}"
        )
    return text


def _model_mapping(document: Any, origin: str) -> Mapping[str, Any]:
    """Return the document's cost model mapping, or refuse the document.

    Precedence is stated rather than guessed (see the module docstring): a
    mapping carrying the ``cost_model`` key is read *through* that key, so
    a larger settings document can hold other sections beside the model;
    anything else that is a mapping is read as the model itself.
    """
    if not isinstance(document, Mapping):
        raise CostModelConfigError(
            f"{origin} is not a cost model document: expected a YAML mapping "
            f"of {_REQUIRED_KEYS[0]!r} and {_REQUIRED_KEYS[1]!r} (optionally "
            f"under a {COST_MODEL_KEY!r} key), got "
            f"{type(document).__name__}"
        )
    block = document.get(COST_MODEL_KEY, document)
    if not isinstance(block, Mapping):
        raise CostModelConfigError(
            f"{origin} carries a {COST_MODEL_KEY!r} key that is not a mapping, "
            f"got {type(block).__name__}"
        )
    return block


def _frozen(value: Any) -> Any:
    """Return ``value`` as a read-only view, all the way down.

    Wrapping the top mapping only would be a guarantee that stops one
    level short of the thing it promises: the model's *sections* are the
    configuration — a fee schedule, a fill model, latency and borrow
    assumptions — so a caller who can write ``document["fees"][...]`` can
    rewrite the very numbers the model resolves to, while a test of the
    top-level mapping still passes.  Every nested mapping is wrapped and
    every list is frozen to a tuple, so read-only means read-only at the
    depth that matters.
    """
    if isinstance(value, Mapping):
        return MappingProxyType({key: _frozen(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_frozen(item) for item in value)
    return value


def _resolve(block: Mapping[str, Any], origin: str) -> dict[str, str]:
    """Pull the two resolved components out of a cost model mapping."""
    resolved: dict[str, str] = {}
    for key in _REQUIRED_KEYS:
        if key not in block:
            raise CostModelConfigError(
                f"{origin} names no cost model {key}: a resolved cost model "
                f"carries both {' and '.join(_REQUIRED_KEYS)}"
            )
        try:
            resolved[key] = _validated_component(block[key], key)
        except CostModelConfigError as exc:
            raise CostModelConfigError(f"{origin}: {exc}") from exc
    return resolved


def read_cost_model_document(
    path: Optional[Union[str, "os.PathLike[str]"]] = None,
) -> tuple[Mapping[str, Any], str]:
    """Parse the YAML document at ``path``; return its model mapping and origin.

    The load's *parsing* half, split out so that
    :func:`load_cost_model` can resolve the identity pair and a later
    consumer can reach the same parsed document without re-reading the
    file.  Feature 60 hashes *the loaded configuration* — the whole §6.2
    document, fee schedule and fill model included, not just the pair
    feature 59 persists — and a hash taken over a fresh re-parse is a hash
    of whatever the file says *now*, which is exactly the divergence the
    provenance triple exists to catch.  Reading once and resolving from the
    one parse is what keeps a score's ``cost_model_hash`` naming the bytes
    its own evaluation used.

    Returns the model mapping (the ``cost_model`` block when the document
    carries one, else the document itself — see the module docstring for
    the precedence) and the origin string naming where it was read from.
    The mapping is a read-only view of the parse at every depth (see
    :func:`_frozen`), so a consumer can hash it or read a nested section
    and cannot mutate it — at the top level or inside a section — into a
    different configuration than the one that was loaded.

    Raises :class:`~cost_model.errors.CostModelConfigError` for every
    document defect :func:`load_cost_model` refuses, and nothing else — a
    missing parser is :class:`ModuleNotFoundError`, as it is there.
    """
    source = Path(path) if path is not None else DEFAULT_COST_MODEL_PATH
    origin = str(source)
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise CostModelConfigError(
            f"could not read the cost model configuration {origin}: {exc}"
        ) from exc
    yaml = require_yaml()
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise CostModelConfigError(
            f"{origin} is not valid YAML: {exc}"
        ) from exc
    if document is None:
        raise CostModelConfigError(
            f"{origin} is empty; a cost model document carries a "
            f"{_REQUIRED_KEYS[0]!r} and a {_REQUIRED_KEYS[1]!r}"
        )
    block = _model_mapping(document, origin)
    return _frozen(block), origin


def load_cost_model(
    path: Optional[Union[str, "os.PathLike[str]"]] = None,
) -> CostModelConfig:
    """Load the YAML cost model at ``path`` and resolve its version and venue.

    ``path`` defaults to :data:`DEFAULT_COST_MODEL_PATH` — the §6.2 document
    this member ships — and is otherwise whatever the caller passes, so an
    operator's signed artifact and the shipped default take exactly the same
    code path.

    Every refusal is a :class:`~cost_model.errors.CostModelConfigError`
    naming the offending value and the contract it broke: a path that cannot
    be read, bytes that are not YAML, an empty document, a document that is
    not a mapping, a ``cost_model`` key that is not one, or a model missing
    (or carrying an unusable) ``version``/``venue``.  The loader never
    substitutes a default for a missing component: a silent fallback version
    would be a fee schedule nothing signed, which is precisely the state §2's
    trust zone exists to prevent.

    The document itself is parsed once, by
    :func:`read_cost_model_document`, which is also the seam a later
    consumer reaches for when it needs more of the configuration than the
    resolved pair — feature 60's hash, or a fee schedule's basis points.
    """
    model, origin = read_cost_model_document(path)
    resolved = _resolve(model, origin)
    return CostModelConfig(
        version=resolved["version"], venue=resolved["venue"], source=origin
    )
