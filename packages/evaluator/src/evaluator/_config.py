"""The resolved configuration — the second term of ``evaluator_hash``.

architecture §6 writes the identity as ``sha256(image_digest + config)`` and
feature 70 spells the second term out as *the resolved configuration*. That
word is doing real work, and this module is where it is honoured.

**Resolved, not declared.** Several layers can state an evaluator's
configuration — the defaults this package ships (:data:`DEFAULT_CONFIG`,
whose horizon set is §6.1 step 4's ``h ∈ {1,2,5,10,20}``), the operator's
configuration document, and any explicit override the process applies. What
the identity must fold is the *outcome* of layering them: two runs that
resolved to the same effective configuration are the same evaluator even if
one of them had to override a default to get there, and two runs whose
documents agreed but whose effective settings did not are different
evaluators. Hashing the declared document instead would make the identity
depend on *how* a setting was reached rather than on what it is — so
:func:`resolve_config` layers the sources first and the formula folds the
result.

**Canonical spelling.** A hash over under-specified bytes is a hash over
nothing — the argument ``snapshot/_identity`` makes for its own terms. A
mapping has no single natural byte spelling: ``{"a":1,"b":2}`` and
``{"b": 2, "a": 1}`` are the same configuration and different strings. So
:func:`canonical_config` pins one: key-sorted, compact JSON
(``separators=(",", ":")``), which makes key order and whitespace
unable to leak into an identity two callers mean to be the same. The same
one-spelling rule serves the deep-merge comparison in :func:`resolve_config`
and the hash, so "the same configuration" cannot mean one thing in a merge
and another in a hash.

**Why JSON, and why the guard rails.** JSON is the medium because the
configuration has to survive a round trip through the persisted row and the
``NULLIUS_EVALUATOR_CONFIG`` override, and JSON is what both can carry
without a schema. That imposes the term's rules: the configuration must be a
JSON object (not a list, not a dataclass — a dataclass is folds-of-fields
with no canonical spelling), its keys must be non-empty strings (a
``None`` key is not a name anyone can override later), and its values must
be JSON round-trippable. Each is refused with a message that says what to
pass instead, at resolution time — before any identity is computed over a
configuration that could not be written down.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, Optional

from ._errors import EvaluatorConfigError

__all__ = [
    "DEFAULT_CONFIG",
    "ENV_CONFIG",
    "EvaluatorConfig",
    "canonical_config",
    "resolve_config",
]

#: The environment variable carrying an operator's configuration override, as
#: a JSON object: ``NULLIUS_EVALUATOR_CONFIG='{"horizons":[1,5,20]}'``.
#:
#: An override here is merged *over* whatever the process was constructed
#: with, so a deployment can adjust one knob without restating the document —
#: and because the merge happens before the hash, the identity an operator
#: gets is the identity of the configuration that actually ran. An empty or
#: whitespace-only value counts as unset, the same way the rest of the
#: workspace treats an empty environment variable.
ENV_CONFIG = "NULLIUS_EVALUATOR_CONFIG"

#: The evaluator's own defaults — the bottom layer of every resolution.
#:
#: Only settings the evaluator itself owns are here, and each is one the
#: architecture states for *its* pipeline: the five forward-return horizons
#: of §6.1 step 4 (feature 75), the ranking-then-z-scoring of step 3
#: (feature 74), and the cross-validation purge and embargo of steps 6 and 7
#: (features 77 and 78). They live in the identity because they are the
#: settings that change what a score *means*: a horizon added or a purge
#: widened is a different evaluator, and §15's failure table treats exactly
#: that as an evaluator change ("Feature definition changed → treat as an
#: evaluator change. This is the sneakiest one").
#:
#: **What is deliberately absent: the fee schedule.** §6.2's ``cost_model``
#: block is tempting to fold in — §6.1 step 7 applies costs inside this
#: pipeline — but it belongs to a different axis of the provenance triple.
#: §14.1 pins ``evaluator_hash``, ``snapshot_hash`` and ``cost_model_hash``
#: as three separate values, and the cost model is its own plugin (features
#: 59-69) with its own configuration and its own hash (feature 60:
#: "persists ``cost_model_hash`` computed over the loaded configuration, so
#: every score names its fee assumptions"). Folding a fee schedule here would
#: make a re-priced venue look like a changed evaluator: every stored score
#: would be reported as cross-evaluator incomparable when in truth only the
#: cost axis moved, and the two hashes §15 relies on to tell those cases
#: apart would stop disagreeing in the way they are meant to. The pipeline
#: *consumes* the cost model; the identity must not *absorb* it.
DEFAULT_CONFIG: Mapping[str, Any] = MappingProxyType(
    {
        "horizons": [1, 2, 5, 10, 20],
        "purge_periods": 20,
        "embargo_periods": 20,
        "normalization": "rank_zscore",
    }
)


def resolve_config(
    *sources: Optional[Mapping[str, Any]],
    defaults: Optional[Mapping[str, Any]] = None,
) -> Mapping[str, Any]:
    """Layer configuration sources into one resolved configuration.

    Later sources win over earlier ones; nested mappings are merged key by
    key rather than replaced wholesale, so an operator adjusting one setting
    inside a nested block keeps its siblings.
    This is the layer where "resolved" is decided — see the module docstring
    for why the identity folds the outcome and not the documents.

    ``defaults`` is the bottom layer (:data:`DEFAULT_CONFIG` when omitted).
    ``None`` sources are skipped, so a caller can pass an optional override
    straight through without a branch at the call site. The result is
    validated and returned behind a read-only proxy, so a caller cannot
    mutate the configuration an identity was computed over after the fact.

    Raises :class:`~evaluator.EvaluatorConfigError` for any layer that is
    not a JSON object of JSON-carryable values — refused at resolution time,
    because a configuration the canonical spelling cannot write down is one
    no identity can name.
    """
    resolved: dict[str, Any] = dict(
        _validate_layer(DEFAULT_CONFIG if defaults is None else defaults, "defaults")
    )
    for index, source in enumerate(sources):
        if source is None:
            continue
        layer = _validate_layer(source, f"configuration source {index}")
        _merge_into(resolved, layer)
    return MappingProxyType(resolved)


def canonical_config(config: Optional[Mapping[str, Any]]) -> str:
    """The canonical JSON spelling of a resolved configuration, for the hash.

    Key-sorted and compact, so two configurations that differ only in key
    order or spacing are one string and therefore one identity. ``None`` is
    refused rather than folded as ``null``: unlike the snapshot formula's
    universe definition — where "not asserted" is a real state a seal can be
    in — an evaluator *always* has a configuration (its defaults are one),
    so a ``None`` here means a caller skipped resolution rather than that
    the evaluator has no settings. Refusing it is cheaper than debugging an
    identity that silently folded "nothing".

    The result is newline-free: ``json.dumps`` escapes control characters
    and never emits one raw, which is what keeps the formula's
    newline-framed preimage separable back into its two terms.
    """
    if config is None:
        raise EvaluatorConfigError(
            "resolved configuration must be a JSON object, got None; an "
            "evaluator always has a configuration — resolve defaults with "
            "evaluate_config() rather than folding 'nothing'"
        )
    return json.dumps(
        dict(_validate_layer(config, "resolved configuration")),
        sort_keys=True,
        separators=(",", ":"),
    )


def _validate_layer(layer: Mapping[str, Any], label: str) -> Mapping[str, Any]:
    """Accept a configuration layer as a JSON object, or refuse it.

    The rules are the minimum the canonical spelling needs — a mapping of
    non-empty string keys to JSON-carryable values — plus the honesty rule
    that a non-object layer would otherwise be silently wrapped or dropped.
    A violation names the label it was found under, because a resolution
    failure that does not say *which* layer is wrong costs a debugging
    session.

    Validation runs over a plain ``dict`` copy, and callers build on that
    copy. This matters because resolution is re-entrant: :func:`resolve_config`
    validates each layer and :func:`canonical_config` validates again what
    resolution produced, and the proxy :func:`resolve_config` returns is not
    itself JSON-serializable — so probing the proxy would refuse every
    configuration that had already been resolved once.
    """
    if not isinstance(layer, Mapping):
        raise EvaluatorConfigError(
            f"{label} must be a JSON object (a mapping of setting names to "
            f"values), got {type(layer).__name__}; pass the mapping form — "
            "for a dataclass, dataclasses.asdict(config)"
        )
    copy = dict(layer)
    for key in copy:
        if not isinstance(key, str) or not key:
            raise EvaluatorConfigError(
                f"{label} carries key {key!r}; configuration keys must be "
                "non-empty strings, because a key is a name an override has "
                "to be able to address"
            )
    try:
        json.dumps(copy, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise EvaluatorConfigError(
            f"{label} is not JSON-serializable: {exc}; the configuration is "
            "folded as canonical JSON and stored alongside the hash, so it "
            "has to be a value the store can re-read"
        ) from exc
    _reject_float_specials(copy, label)
    return copy


def _reject_float_specials(value: Any, label: str) -> None:
    """Refuse ``NaN``/``Infinity``, which ``json.dumps`` writes but JSON forbids.

    Python's ``json`` emits the bare literals ``NaN``, ``Infinity`` and
    ``-Infinity`` by default — text no conforming JSON reader accepts, and
    which the ``json.loads`` on the read path happens to accept back, so the
    disagreement would only surface against a different reader (a Postgres
    ``JSONB`` column, an operator's tooling). Worse, they are not equal to
    themselves: a folded ``NaN`` makes two identical configurations compare
    unequal, which is exactly the failure a provenance hash exists to prevent.
    """
    if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
        raise EvaluatorConfigError(
            f"{label} carries the non-finite float {value!r}; JSON has no "
            "spelling for NaN or Infinity, and such a value is not equal to "
            "itself, so two identical configurations would compare unequal"
        )
    if isinstance(value, Mapping):
        for key, item in value.items():
            _reject_float_specials(item, f"{label}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_float_specials(item, f"{label}[{index}]")


def _merge_into(target: dict[str, Any], layer: Mapping[str, Any]) -> None:
    """Deep-merge one validated layer over an accumulator, in place.

    Nested mappings merge; everything else replaces. A list is *replaced*
    rather than concatenated or element-merged on purpose: the horizon set is
    §6.1 step 4's ``{1,2,5,10,20}``, and an operator who configures
    ``[1,5,20]`` means exactly those three horizons — merging element-wise
    would make the effective set depend on the default's length, which is
    the kind of quiet coupling an identity term must not have.
    """
    for key, value in layer.items():
        existing = target.get(key)
        if isinstance(existing, Mapping) and isinstance(value, Mapping):
            merged = dict(existing)
            _merge_into(merged, value)
            target[key] = merged
        else:
            target[key] = value


class EvaluatorConfig:
    """The evaluator's configuration, layered and resolved in one place.

    A thin binding over :func:`resolve_config` that captures the sources at
    construction and answers with the resolved configuration — so the
    identity a service computes and the configuration an operator inspects
    are the same object, spelled once.

    The sources are held, not merged, until :meth:`resolved` is called: a
    service built at composition time performs no JSON work, and a caller
    that only wants the defaults never pays for resolution.
    """

    def __init__(
        self,
        declared: Optional[Mapping[str, Any]] = None,
        *,
        overrides: Optional[Mapping[str, Any]] = None,
        defaults: Optional[Mapping[str, Any]] = None,
        env: Optional[Mapping[str, str]] = None,
    ) -> None:
        self._declared = declared
        self._overrides = overrides
        self._defaults = defaults
        # The environment is *held*, not read — even its override value is
        # parsed lazily (see :meth:`_env_overrides`). That is deliberate: the
        # factory builds this component on every ``create_app()``, so a
        # malformed NULLIUS_EVALUATOR_CONFIG must not take down composition
        # for every unrelated feature in the workspace. It fails where it can
        # be acted on — at the first resolution — which is also where the
        # image and store refusals land (see ``_service``).
        self._env = env

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "EvaluatorConfig":
        """Construct the configuration the process is pointed at.

        ``NULLIUS_EVALUATOR_CONFIG``, when set and non-empty, is applied as
        the top override layer (see :data:`ENV_CONFIG`). The value is parsed
        on first :meth:`resolved` rather than here, so construction stays
        free of both I/O and JSON work; see :meth:`_env_overrides` for the
        parse and its refusals.
        """
        return cls(env=env)

    @property
    def declared(self) -> Optional[Mapping[str, Any]]:
        """The operator's configuration document, as given (unresolved)."""
        return self._declared

    def _env_overrides(self) -> Optional[Mapping[str, Any]]:
        """Parse ``NULLIUS_EVALUATOR_CONFIG``, or explain why it cannot be.

        Read from the environment the config was constructed with (the
        process environment when it was given none). A value that is not a
        JSON object is refused — including valid JSON that is a list or a
        scalar, which would otherwise merge as a layer the rules never
        contemplated — with a message showing the expected shape. An absent
        or blank value means no override layer at all, the same way the rest
        of the workspace treats an empty environment variable.
        """
        import os

        source = os.environ if self._env is None else self._env
        raw = source.get(ENV_CONFIG, "")
        if raw is None or not raw.strip():
            return None
        try:
            parsed = json.loads(raw)
        except ValueError as exc:
            raise EvaluatorConfigError(
                f"{ENV_CONFIG} is not valid JSON: {exc}; expected a JSON "
                'object of settings, for example \'{"horizons":[1,5,20]}\''
            ) from exc
        if not isinstance(parsed, dict):
            raise EvaluatorConfigError(
                f"{ENV_CONFIG} must be a JSON object, got "
                f"{type(parsed).__name__}; an override layer merges over the "
                "defaults, and only an object can be merged"
            )
        return parsed

    def resolved(self) -> Mapping[str, Any]:
        """The resolved configuration — defaults, declared, then overrides.

        The environment override (when configured) is the top layer, above
        even an explicit ``overrides`` mapping: a deployment's environment
        states what the process is *actually* pointed at, so it must not be
        silently beaten by a value captured somewhere else.
        """
        return resolve_config(
            self._declared,
            self._overrides,
            self._env_overrides(),
            defaults=self._defaults,
        )

    def canonical(self) -> str:
        """The canonical JSON spelling of the resolved configuration."""
        return canonical_config(self.resolved())

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"EvaluatorConfig(declared={self._declared!r})"
