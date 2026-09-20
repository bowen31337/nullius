"""The ``cost_model_hash`` formula: one identity over the loaded configuration.

app_spec.xml, "Cost Model & Fill Simulation", feature 60: *System persists
``cost_model_hash`` computed over the loaded configuration, so every score
names its fee assumptions.*  docs/nullius-tech-architecture.md §6.2 gives the
value its purpose in one line — *"``cost_model_hash`` is part of every
score's provenance triple"* — and §14.1 pins it as one of three axes a score
comparison ranks against: two scores whose cost models disagree are not the
same measurement and are never compared (``docs/alpha-engine-prd.md`` §13.5).

**What the hash is over, and what it is not.**  Feature 59 persists the
``(venue, version)`` pair; feature 60 pins the *bytes*.  The distinction is
not pedantry — a pair is a label its author chose, and two documents can
carry the same label while pricing differently (a rate edited without a
version bump, an operator's scratch copy, a hand-edited artifact).  A score
stamped with the pair alone would then look comparable to a score priced
against other fees.  So the hash is taken over the whole loaded model — the
fee schedule, the fill model, latency and borrow assumptions, *and* the
``version``/``venue`` labels themselves — and the pair becomes one of the
things the hash covers rather than all of it.

The configuration folded is the model mapping
:func:`~cost_model.config.read_cost_model_document` returns, which is the
``cost_model`` block when the document carries one and the document itself
otherwise.  That is deliberate: a larger settings file wrapping the model
under ``cost_model:`` is *the same cost model* as a bare document carrying
those bytes, and folding the wrapper's other sections in would make the hash
move for reasons that have nothing to do with fees.  The model block is what
§6.2 fixes, so the model block is what is folded.

**The canonical spelling is the format.**  A hash over under-specified bytes
is a hash over nothing, so the preimage is pinned: the configuration is
rendered as JSON with its keys sorted and no incidental whitespace
(:func:`canonical_cost_model`), encoded UTF-8, and hashed once.  Two
documents that differ only in key order, indentation or comments are one
configuration and therefore one hash, which is what makes the value name a
set of *assumptions* rather than a file.  Comments in particular never reach
the formula: YAML discards them, and a hash that read the file's text would
move when someone annotated a signed artifact.

Unlike §4.2's ``snapshot_hash`` and §6's ``evaluator_hash``, this formula has
one term, so there is no joining separator to pin.  Those formulas frame
their terms with a newline so the preimage can be split back into exactly the
terms that produced it; a single term needs no such guarantee, and adding
one would be punctuation that means nothing.

**Deterministic the way a comparison requires.**  The same configuration
produces the same hash on any machine, any day, in any process — that is what
lets a stored row be checked against a score's stamp at all.  The value is
therefore 64 lowercase hex characters, the spelling the spec's
``cost_model_hash CHAR(64) NOT NULL`` columns hold, and
:func:`normalize_cost_model_hash` is the one place that spelling is enforced
— matching the treatment ``snapshot.normalize_snapshot_hash`` and
``evaluator.normalize_evaluator_hash`` give the sibling columns.

**What it cannot do.**  The hash proves two scores priced against the same
bytes; it does not prove the bytes are the signed ones.  The Z0 trust zone's
read-only mount and signed release (docs/nullius-tech-architecture.md §2) are
that boundary, and feature 60's sentence stops at writing down the identity
of what was loaded.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from typing import Any

from .errors import CostModelConfigError

__all__ = [
    "COST_MODEL_HASH_LENGTH",
    "canonical_cost_model",
    "cost_model_digest",
    "normalize_cost_model_hash",
]

#: Length of the persisted ``cost_model_hash`` — a sha256 hex digest, matching
#: the spec's ``cost_model_hash CHAR(64) NOT NULL`` columns on ``node`` and
#: ``trial_ledger``.
COST_MODEL_HASH_LENGTH = 64

_HEX = frozenset("0123456789abcdef")


def _plain(value: Any, path: str) -> Any:
    """Return ``value`` as a plain JSON-carryable structure, or refuse it.

    The frozen model :func:`~cost_model.config.read_cost_model_document`
    returns is read-only all the way down — mappings behind proxies, lists as
    tuples — and :func:`json.dumps` cannot serialize a proxy, so the
    canonical spelling needs this conversion before it can render anything.
    The conversion is also where the *unspeakable* is refused: JSON is the
    canonical form, so a value JSON cannot carry is a value the hash cannot
    pin, and pinning "something" in its place would be a hash over bytes
    nobody can reproduce.

    The refusals are the two YAML can produce that JSON cannot, plus the two
    JSON can only carry badly:

    * a scalar JSON has no form for — a ``!!binary`` blob's :class:`bytes`, a
      bare date's :class:`datetime.date`, a ``!!set``.  Refused with the path
      and the fix (quote it, so it is read as the text the document
      carries), the same advice :class:`~cost_model.config.CostModelConfig`
      gives a numeric version.
    * a key that is not a non-empty string — YAML happily reads ``1: x`` as
      an integer key, and a mapping keyed half by strings and half by
      integers is not sorted by :func:`json.dumps` at all (it raises on the
      comparison), so the canonical spelling would be unavailable exactly
      when the document is odd.  A key is a name a section is addressed by,
      which is the argument ``evaluator._config`` makes for the same rule.
    * a non-finite :class:`float` — ``.nan``, ``.inf``.  ``json.dumps``
      renders them as ``NaN``/``Infinity``, which is not JSON, and ``NaN``
      is not even equal to itself: a cost model whose fee cannot be compared
      to its own reload is not a pinned configuration.  Every other number
      in this package refuses non-finiteness by name (see
      :class:`~cost_model.queue_penalty.QueuePositionPenaltyModel`), and the
      document half is no different.
    """
    if isinstance(value, Mapping):
        plain: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key:
                raise CostModelConfigError(
                    f"the cost model's {path or 'root'} carries the key "
                    f"{key!r}; a configuration key must be a non-empty string, "
                    "because the canonical spelling sorts keys and a key is "
                    "the name a section is addressed by"
                )
            plain[key] = _plain(item, f"{path}.{key}" if path else key)
        return plain
    if isinstance(value, (list, tuple)):
        return [_plain(item, f"{path}[{index}]") for index, item in enumerate(value)]
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CostModelConfigError(
                f"the cost model's {path or 'root'} is {value!r}; the "
                "configuration is hashed through its canonical JSON spelling, "
                "which has no form for a non-finite number — write the fee as "
                "the finite real the document means"
            )
        return value
    raise CostModelConfigError(
        f"the cost model's {path or 'root'} is a {type(value).__name__}, which "
        "the canonical JSON spelling cannot carry; quote it in the YAML so it "
        "is read as the text the document carries, because a value the hash "
        "cannot pin is a value no score could name"
    )


def canonical_cost_model(model: Mapping[str, Any]) -> str:
    """The canonical JSON spelling of a loaded cost model, for the hash.

    Key-sorted and compact, so two configurations that differ only in key
    order, indentation or spacing are one string and therefore one identity.
    The result is what :func:`cost_model_digest` hashes, and it is exposed
    because a hash whose preimage cannot be printed is a hash nobody can
    debug: an operator asking *why did this score's stamp move* needs to see
    the two spellings that differ.

    Raises :class:`~cost_model.errors.CostModelConfigError` naming the path
    of the offending value when the model carries something JSON cannot
    carry — see :func:`_plain`, which is the whole of that contract.
    """
    return json.dumps(_plain(model, ""), sort_keys=True, separators=(",", ":"))


def cost_model_digest(model: Mapping[str, Any]) -> str:
    """Compute feature 60's ``cost_model_hash`` over a loaded configuration.

    ``model`` is the loaded model mapping — the ``cost_model`` block when the
    document carries one, else the document itself, exactly what
    :func:`~cost_model.config.read_cost_model_document` returns and
    :func:`~cost_model.config.load_cost_model` folds from its one parse.
    Returns 64 lowercase hex characters — the value feature 60 persists and
    a score names.

    Deliberately given a *parsed* configuration rather than a path: hashing a
    fresh re-read would name whatever the file says now, which is the
    divergence the provenance triple exists to catch (the argument
    ``config.read_cost_model_document`` makes for splitting the parse out).
    A caller holding a path wants
    :func:`~cost_model.config.load_cost_model`, which is the single-parse
    seam that computes this over the bytes it resolved the identity from.
    """
    return hashlib.sha256(canonical_cost_model(model).encode("utf-8")).hexdigest()


def normalize_cost_model_hash(value: str) -> str:
    """Validate a ``cost_model_hash``, returning it in canonical lowercase hex.

    Accepts 64 hexadecimal characters in either case — a hash pasted from a
    database, a log line or a report is commonly uppercase, means the same
    value, and uppercasing is normalized away rather than refused — matching
    the treatment ``snapshot.normalize_snapshot_hash`` and
    ``evaluator.normalize_evaluator_hash`` give the sibling columns.  Rejects
    a ``sha256:``-prefixed digest (that spelling belongs to an image
    reference, and accepting it here would let a caller compare a digest
    against a hash and get "different" for the wrong reason), a short hash,
    and anything of the wrong length or alphabet.

    The refusal is a :class:`~cost_model.errors.CostModelConfigError`: a
    malformed hash is a mistake in a *value* — a stamp that names no
    configuration — refused on whoever supplied it, which is the same
    contract that error already carries for a malformed ``version``.  The
    message distinguishes the three ways a token fails, because "not 64 hex
    characters" alone does not tell an operator whether they pasted a git
    short hash, a truncated column or an image digest.
    """
    if not isinstance(value, str):
        raise CostModelConfigError(
            f"cost_model_hash must be a {COST_MODEL_HASH_LENGTH}-character hex "
            f"string, got {type(value).__name__}"
        )
    text = value.strip()
    if ":" in text:
        raise CostModelConfigError(
            f"cost_model_hash {value!r} carries an algorithm prefix; a "
            "sha256:<hex> digest belongs to an image reference, not to the "
            "hash computed over a cost model — pass the 64 hex characters "
            "themselves"
        )
    if len(text) != COST_MODEL_HASH_LENGTH or not set(text.lower()) <= _HEX:
        raise CostModelConfigError(
            f"cost_model_hash {value!r} is not {COST_MODEL_HASH_LENGTH} hex "
            "characters; a short hash, a truncated value or a non-hex token "
            "names no configuration this system recorded"
        )
    return text.lower()
