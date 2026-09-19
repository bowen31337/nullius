"""The §4.2 snapshot hash: one identity over content, universe and schema.

These are the acceptance tests for app_spec.xml feature 32 — "System
persists snapshot_hash computed as a sha256 over sorted file hashes plus
the universe definition plus the schema version". Each clause of that
sentence is pinned below:

* *sha256 over sorted file hashes* — the fold is order-independent and
  path-independent, and its spelling is the one ``_content`` already
  defines (``sorted_hash_concat``), so the formula's first term and the
  bare content digest cannot drift apart.
* *plus the universe definition* — folded by value through the canonical
  JSON spelling, so key order and whitespace are not identity, while
  ``None`` (nothing asserted), ``{}`` (an asserted empty definition) and
  any real definition remain three different claims.
* *plus the schema version* — :data:`SCHEMA_VERSION` is a term like any
  other, so bumping it re-keys every seal without touching a byte of
  content that has not changed.
* *persists* — the seal's default identity *is* this formula, and the
  value lands on disk in ``MANIFEST.json``, so the lake rather than the
  sealer's memory holds it.

The preimage's byte-level spelling is the format, so it is spelled out
here independently of the implementation: the three terms joined by single
newlines and hashed once as UTF-8. The term-by-term separability that
framing buys is pinned too — a universe spelling cannot be re-split as a
schema version, because neither term can carry the newline that separates
them.

The formula module (``_identity``) is imported through the member's public
surface (``snapshot``) wherever the public surface carries the name; the
pieces that are deliberately internal (``validate_universe``) are reached
through the module, because a test for an internal door should say which
door it is opening.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping, Optional

import pytest
from snapshot import (
    MANIFEST_NAME,
    SCHEMA_VERSION,
    SnapshotManifestError,
    SnapshotNameError,
    SnapshotService,
    canonical_universe,
    content_digest,
    snapshot_digest,
)
from snapshot._identity import validate_universe

BTC_PART_0 = b"BTCUSDT-2026-09-01-part-0"
BTC_PART_1 = b"BTCUSDT-2026-09-01-part-1"
ETH_PART_0 = b"ETHUSDT-2026-09-01-part-0"

UNIVERSE = {
    "definition": "top_n_by_median_dollar_volume",
    "top_n": 2,
    "window_days": 30,
    "effective_from": "2026-09-01",
    "symbols": ["BTCUSDT", "ETHUSDT"],
}

# Two definitions that differ only in key insertion order: one identity.
UNIVERSE_REORDERED = dict(reversed(list(UNIVERSE.items())))


def _hashes(*payloads: bytes) -> list[str]:
    return [hashlib.sha256(payload).hexdigest() for payload in payloads]


def _formula(
    file_hashes: list[str],
    universe: Optional[Mapping[str, object]] = None,
    schema_version: str = SCHEMA_VERSION,
) -> str:
    """The §4.2 formula, spelled out independently of the implementation.

    Deliberately not a call into ``snapshot_digest``: this is the spec
    written a second time, so the test fails when the implementation and
    the spec disagree rather than when they agree with each other.
    """
    universe_term = (
        "null"
        if universe is None
        else json.dumps(dict(universe), sort_keys=True, separators=(",", ":"))
    )
    preimage = "\n".join(
        ("".join(sorted(file_hashes)), universe_term, schema_version)
    ).encode("utf-8")
    return hashlib.sha256(preimage).hexdigest()


# ---------------------------------------------------------------------------
# The formula itself
# ---------------------------------------------------------------------------


class TestTheFormula:
    def test_it_is_the_spec_spelled_out(self) -> None:
        hashes = _hashes(BTC_PART_0, BTC_PART_1, ETH_PART_0)
        assert snapshot_digest(hashes, universe=UNIVERSE) == _formula(
            hashes, UNIVERSE
        )

    def test_the_three_terms_are_all_in_the_preimage(self) -> None:
        # Each term moves the hash: none is folded in name only.
        hashes = _hashes(BTC_PART_0)
        baseline = snapshot_digest(hashes, universe=None)
        assert snapshot_digest(hashes, universe=UNIVERSE) != baseline
        assert snapshot_digest(hashes, universe={}) != baseline
        assert snapshot_digest(hashes, schema_version="2") != baseline
        assert snapshot_digest(_hashes(BTC_PART_1), universe=None) != baseline

    def test_the_mapping_form_and_the_iterable_form_agree(self) -> None:
        # walk_content's {path: sha256} mapping passes straight through.
        mapping = {
            "bars/symbol=BTCUSDT/date=2026-09-01/part-0.parquet": hashlib.sha256(
                BTC_PART_0
            ).hexdigest(),
            "bars/symbol=ETHUSDT/date=2026-09-01/part-0.parquet": hashlib.sha256(
                ETH_PART_0
            ).hexdigest(),
        }
        assert snapshot_digest(mapping, universe=UNIVERSE) == snapshot_digest(
            list(mapping.values()), universe=UNIVERSE
        )

    def test_the_fold_is_over_hashes_alone_not_paths(self) -> None:
        # §4.2 reads ``sorted(file_hashes)``: two snapshots whose files
        # swapped names but kept the bytes are one identity, here as in
        # ``content_digest``.
        left = {"a.parquet": "1" * 64, "b.parquet": "2" * 64}
        right = {"a.parquet": "2" * 64, "b.parquet": "1" * 64}
        assert snapshot_digest(left, universe=UNIVERSE) == snapshot_digest(
            right, universe=UNIVERSE
        )

    def test_the_first_term_is_the_content_digest_preimage(self) -> None:
        # Not an equality with ``content_digest`` (the formula adds two
        # terms), but a shared fold: the formula's first term is exactly
        # the string ``content_digest`` hashes — the sorted hashes,
        # concatenated as lowercase hex — so the two spellings cannot
        # drift apart.
        hashes = _hashes(BTC_PART_0, ETH_PART_0)
        assert content_digest(hashes) == hashlib.sha256(
            "".join(sorted(hashes)).encode("ascii")
        ).hexdigest()
        assert snapshot_digest(hashes) != content_digest(hashes)

    def test_an_empty_snapshot_is_still_addressed_by_the_other_terms(self) -> None:
        assert snapshot_digest([]) == _formula([])
        assert snapshot_digest([]) != hashlib.sha256(b"").hexdigest()

    def test_it_is_deterministic_across_calls(self) -> None:
        hashes = _hashes(BTC_PART_0, ETH_PART_0)
        assert snapshot_digest(hashes, universe=UNIVERSE) == snapshot_digest(
            list(reversed(hashes)), universe=UNIVERSE
        )


# ---------------------------------------------------------------------------
# The universe term
# ---------------------------------------------------------------------------


class TestTheUniverseTerm:
    def test_key_order_is_not_identity(self) -> None:
        hashes = _hashes(BTC_PART_0)
        assert snapshot_digest(hashes, universe=UNIVERSE) == snapshot_digest(
            hashes, universe=UNIVERSE_REORDERED
        )

    def test_none_empty_and_a_definition_are_three_claims(self) -> None:
        hashes = _hashes(BTC_PART_0)
        digests = {
            snapshot_digest(hashes, universe=None),
            snapshot_digest(hashes, universe={}),
            snapshot_digest(hashes, universe=UNIVERSE),
        }
        assert len(digests) == 3

    def test_the_nested_definition_is_folded_by_value(self) -> None:
        # The universe member's asdict form carries nested lists; two
        # definitions differing inside them are different identities.
        hashes = _hashes(BTC_PART_0)
        widened = dict(UNIVERSE, symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
        assert snapshot_digest(hashes, universe=UNIVERSE) != snapshot_digest(
            hashes, universe=widened
        )

    def test_canonical_universe_is_key_sorted_compact_json(self) -> None:
        assert canonical_universe(UNIVERSE) == json.dumps(
            UNIVERSE, sort_keys=True, separators=(",", ":")
        )
        assert canonical_universe(None) is None

    def test_canonical_universe_refuses_a_non_mapping(self) -> None:
        with pytest.raises(SnapshotManifestError, match="JSON object"):
            canonical_universe(["BTCUSDT"])  # type: ignore[arg-type]

    def test_a_non_mapping_universe_is_refused_by_the_formula(self) -> None:
        with pytest.raises(SnapshotManifestError, match="JSON object"):
            snapshot_digest([], universe=["BTCUSDT"])  # type: ignore[arg-type]

    def test_an_unserialisable_universe_is_refused_by_the_formula(self) -> None:
        with pytest.raises(SnapshotManifestError, match="JSON-serializable"):
            snapshot_digest([], universe={"symbols": {"BTCUSDT"}})  # type: ignore[dict-item]


class TestValidateUniverseDoor:
    """The private acceptance door: what it accepts, and what it returns."""

    def test_none_passes_through_as_none(self) -> None:
        assert validate_universe(None) is None

    def test_an_accepted_definition_comes_back_read_only(self) -> None:
        validated = validate_universe(UNIVERSE)
        assert validated == UNIVERSE
        with pytest.raises(TypeError):
            validated["top_n"] = 3  # type: ignore[index]

    def test_the_door_accepts_its_own_output(self) -> None:
        # Validation is re-entrant in practice: the service validates at
        # seal time and the manifest validates again in __post_init__.
        # A door that refused its own output would refuse every seal.
        once = validate_universe(UNIVERSE)
        assert validate_universe(once) == UNIVERSE
        assert canonical_universe(once) == canonical_universe(UNIVERSE)
        assert snapshot_digest([], universe=once) == snapshot_digest(
            [], universe=UNIVERSE
        )

    def test_the_accepted_value_is_a_copy(self) -> None:
        # The proxy is built over the door's own snapshot of the input, so
        # a caller mutating their dict afterwards cannot change what was
        # validated — the hash folded the definition as it was asserted.
        caller_mapping = dict(UNIVERSE)
        validated = validate_universe(caller_mapping)
        caller_mapping["top_n"] = 99
        assert validated["top_n"] == 2


# ---------------------------------------------------------------------------
# The schema version term
# ---------------------------------------------------------------------------


class TestTheSchemaVersionTerm:
    def test_the_module_constant_ships_a_usable_version(self) -> None:
        assert isinstance(SCHEMA_VERSION, str) and SCHEMA_VERSION

    def test_the_parameter_recomputes_under_another_version(self) -> None:
        hashes = _hashes(BTC_PART_0)
        assert snapshot_digest(hashes, schema_version="7") == _formula(
            hashes, schema_version="7"
        )
        assert snapshot_digest(hashes) != snapshot_digest(hashes, schema_version="7")

    @pytest.mark.parametrize("bad", ["", None, 1, b"1"])
    def test_a_non_string_or_empty_version_is_refused(self, bad: object) -> None:
        with pytest.raises(SnapshotNameError, match="non-empty string"):
            snapshot_digest([], schema_version=bad)  # type: ignore[arg-type]

    @pytest.mark.parametrize("bad", ["1\n2", "1\x00", "1\x7f", "1\t2"])
    def test_a_control_bearing_version_is_refused(self, bad: str) -> None:
        # A version carrying a newline could re-split the preimage, which
        # is the one thing the framing guarantees against.
        with pytest.raises(SnapshotNameError, match="control characters"):
            snapshot_digest([], schema_version=bad)

    def test_the_framing_keeps_the_terms_separable(self) -> None:
        # The separability claim, exercised: a universe spelling and a
        # schema version cannot trade characters across the newline,
        # because every spelling of each term that could is refused. If
        # the terms were merely concatenated, these two inputs could
        # collide; framed and validated, they cannot.
        hashes = _hashes(BTC_PART_0)
        with pytest.raises(SnapshotNameError):
            snapshot_digest(hashes, schema_version="1\nnull")
        # …while the well-formed pair is a perfectly ordinary identity.
        assert snapshot_digest(hashes, schema_version="1") == _formula(
            hashes, schema_version="1"
        )


# ---------------------------------------------------------------------------
# Persistence: the seal's default identity is this formula
# ---------------------------------------------------------------------------


class TestTheSealPersistsIt:
    def test_the_default_seal_hash_is_the_formula_over_its_own_walk(
        self, service: SnapshotService, staged: Path
    ) -> None:
        record = service.seal(staged, sealed_at=None)
        assert record.snapshot_hash == snapshot_digest(
            record.files, universe=None, schema_version=SCHEMA_VERSION
        )
        assert record.snapshot_hash != content_digest(record.files)

    def test_the_persisted_manifest_carries_the_value_the_name_abbreviates(
        self, service: SnapshotService, staged: Path
    ) -> None:
        record = service.seal(staged, universe=UNIVERSE)
        payload = json.loads((record.path / MANIFEST_NAME).read_text())
        assert payload["snapshot_hash"] == record.snapshot_hash
        assert record.path.name.endswith(f"_{record.snapshot_hash[:6]}")
        # …and the manifest's universe is what the hash folded.
        assert payload["universe"] == UNIVERSE
        assert record.snapshot_hash == snapshot_digest(
            record.files, universe=payload["universe"]
        )

    def test_the_same_bytes_under_a_bumped_schema_re_key(self) -> None:
        # Feature 38's invalidation lever, at this feature's boundary: the
        # identical content under a new schema version is a different
        # snapshot, addressed by its own name. The seal itself is bound to
        # the module constant (below), so the re-key a schema bump buys is
        # a deliberate edit to :data:`SCHEMA_VERSION`, not something a
        # caller can arrange per-seal.
        hashes = _hashes(BTC_PART_0, ETH_PART_0)
        assert snapshot_digest(hashes, universe=UNIVERSE) != snapshot_digest(
            hashes, universe=UNIVERSE, schema_version="2"
        )

    def test_a_seal_cannot_pick_its_own_schema_version(
        self, service: SnapshotService, staged: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Rebinding the module constant does not re-key a seal: the seal's
        # call binds the default when ``_identity`` is defined. A seal that
        # quietly chose its own version would be a snapshot whose identity
        # the lake cannot reproduce.
        import snapshot._identity as identity

        before = service.seal(staged, universe=UNIVERSE)
        monkeypatch.setattr(identity, "SCHEMA_VERSION", "2")
        after = service.seal(staged, universe=UNIVERSE)

        assert after.snapshot_hash == before.snapshot_hash
        assert after.path == before.path
        assert service.read_manifest(before.name).snapshot_hash == (
            before.snapshot_hash
        )

    def test_a_reader_can_recompute_the_persisted_identity(
        self, service: SnapshotService, staged: Path
    ) -> None:
        # What a verification pass (feature 36) does: read the manifest,
        # re-run the formula over the recorded files and definition, and
        # land on the recorded hash.
        record = service.seal(staged, universe=UNIVERSE)
        manifest = service.read_manifest(record.name)
        assert snapshot_digest(
            {path: entry.sha256 for path, entry in manifest.files.items()},
            universe=manifest.universe,
        ) == manifest.snapshot_hash
