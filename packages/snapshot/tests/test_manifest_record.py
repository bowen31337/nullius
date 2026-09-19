"""Feature 33 — every sealed snapshot is persisted into snapshot_manifest.

The acceptance tests for app_spec.xml feature 33: *"System persists each
sealed snapshot into the snapshot_manifest record so a score can name the
exact bytes it was computed over."* The suite is organised by the clauses
of that sentence, since each is a separate claim:

* *persists each sealed snapshot into the snapshot_manifest record* — a
  seal writes a row into the table the spec's schema block declares, with
  the spec's six columns populated from the snapshot it just published,
  and the row is durable: a second service, built fresh, reads it back.
  Re-sealing the same bytes leaves one row, not two — the primary key is
  the snapshot hash, and an idempotent seal is one identity.
* *so a score can name the exact bytes it was computed over* — the part
  that is easy to fake. The spec's six columns do **not** pin bytes on
  their own: two file trees can share a file count, a row count, a
  universe definition and a schema version and still be different bytes.
  So the tests below build exactly that pair of trees — same shape, same
  counts, different content — and assert that their hashes and their
  ``content_digest`` records differ, and that neither hash's row resolves
  to the other's bytes. The ``§4.2`` formula is a multiset fold and is
  blind to which path holds which bytes; the record is not, and the pair
  of snapshots whose files swapped names is the case that separates them.
* *the record is written once and never edited* — the row is the second
  copy that makes a wholesale manifest rewrite detectable. The tests pin
  both directions of the comparison: bytes that no longer digest to the
  row's ``content_digest``, and a MANIFEST.json whose own bytes no longer
  hash to the recorded ``manifest_digest``.

* *each sealed snapshot* — the word doing the most work in the sentence.
  A snapshot whose files include an opaque binary has no total row count
  (the manifest refuses to invent one), and it is still recorded: the row's
  ``row_count`` is ``NULL``, mirroring the manifest's own ``None`` field for
  field. Skipping the row — the first implementation's choice, to keep the
  column ``NOT NULL`` — is pinned *against* here, because it would leave
  exactly those snapshots' bytes unnameable, which is the one thing the
  feature exists to provide.

Several states that are *not* failures are pinned too, because treating
them as failures is the easy bug: a lake with no ``DATABASE_URL`` seals and
mounts with no record asked for; a pre-manifest snapshot has no full hash
and so no row, reported as an absence rather than a crash; and a manifest
written before this feature — valid JSON of the same manifest version,
without the ``content_digest`` key — still opens, because refusing every
tree sealed earlier in the same version would be a compatibility break
disguised as strictness.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest
from snapshot import (
    DATABASE_URL_ENV,
    MANIFEST_NAME,
    MANIFEST_TABLE,
    SCHEMA_VERSION,
    SnapshotManifestRecord,
    SnapshotManifestStore,
    SnapshotService,
    SnapshotStoreError,
    files_digest,
)

UTC = timezone.utc
AT = datetime(2026, 9, 1, tzinfo=UTC)
HASH = "a3f91c" + "0" * 58


def _unfreeze(path: Path) -> None:
    """Grant the write bit a sealed file's owner needs to tamper with it.

    The documented crack ``_mount`` states: the frozen ``0444`` modes are
    ownership-governed, so the sealing user can chmod them away. Every test
    that simulates tampering has to take that step explicitly, and taking it
    explicitly is the point — the tests are exercising the *post-crack*
    world that features 33 and 36 exist to detect in.
    """
    os.chmod(path, 0o644)


def _refreeze(path: Path) -> None:
    """Put the sealed mode back, so the tree is left as it was found."""
    os.chmod(path, 0o444)


def _rows(database_url: str, snapshot_hash: str) -> list[tuple]:
    """Read the raw rows for one hash, straight from the database.

    Deliberately not through the store's own API: the assertions below are
    that the *table* holds what the spec says it holds, and reading it back
    through the code under test would let a bug in the reader mask a bug in
    the writer.

    A table that does not exist yet counts as no rows, and the database file
    itself may not exist either — the schema is created on first *write*,
    so a lake whose store was never used has neither. Reporting that as an
    empty result rather than an error is what lets the repair tests below
    assert "no row" about a store that has not yet been touched at all.
    """
    path = Path(database_url.removeprefix("sqlite:///"))
    if not path.exists():
        return []
    with sqlite3.connect(path) as connection:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (MANIFEST_TABLE,),
        ).fetchone()
        if exists is None:
            return []
        return connection.execute(
            f"SELECT snapshot_hash, sealed_at, file_count, row_count, "
            f"universe_definition, schema_version, content_digest, "
            f"manifest_digest, manifest_version FROM {MANIFEST_TABLE} "
            "WHERE snapshot_hash = ?",
            (snapshot_hash,),
        ).fetchall()


def _column_names(database_url: str) -> set[str]:
    path = database_url.removeprefix("sqlite:///")
    with sqlite3.connect(path) as connection:
        return {
            row[1]
            for row in connection.execute(f"PRAGMA table_info({MANIFEST_TABLE})")
        }


class TestTheSealWritesTheRow:
    def test_a_sealed_snapshot_gets_a_row(
        self, service: SnapshotService, staged: Path, test_database_url: str
    ) -> None:
        record = service.seal(staged, sealed_at=AT)

        rows = _rows(test_database_url, record.snapshot_hash)
        assert len(rows) == 1
        (
            snapshot_hash,
            sealed_at,
            file_count,
            row_count,
            universe_definition,
            schema_version,
            _content_digest,
            _manifest_digest,
            manifest_version,
        ) = rows[0]
        assert snapshot_hash == record.snapshot_hash
        assert sealed_at == "2026-09-01T00:00:00Z"
        assert file_count == len(record.files) == 3
        # The fixture's staged parts are single-line text with no trailing
        # newline, so each counts one row — the same count the manifest
        # records, read from the file's own format.
        assert row_count == service.read_manifest(record.name).total_rows == 3
        assert json.loads(universe_definition) is None  # no definition asserted
        assert schema_version == SCHEMA_VERSION
        assert manifest_version == 1

    def test_the_table_is_the_specs_table(
        self, service: SnapshotService, staged: Path, test_database_url: str
    ) -> None:
        service.seal(staged, sealed_at=AT)

        # The spec's six columns are all present, under the spec's names.
        assert {
            "snapshot_hash",
            "sealed_at",
            "file_count",
            "row_count",
            "universe_definition",
            "schema_version",
        } <= _column_names(test_database_url)

    def test_the_row_carries_the_universe_and_schema_the_identity_folded(
        self, service: SnapshotService, staged: Path, test_database_url: str
    ) -> None:
        universe = {"top_n": 100, "window_days": 30, "min_dollar_volume": 1.0}
        record = service.seal(staged, sealed_at=AT, universe=universe)

        (row,) = _rows(test_database_url, record.snapshot_hash)
        # The column carries the canonical spelling — the same one the
        # §4.2 hash folds — not whatever key order the caller passed.
        assert json.loads(row[4]) == universe
        assert row[4] == json.dumps(universe, sort_keys=True, separators=(",", ":"))
        assert row[5] == SCHEMA_VERSION

    def test_the_row_records_the_row_counts_the_manifest_read(
        self, service: SnapshotService, lake_root: Path, test_database_url: str
    ) -> None:
        staging = lake_root / "staging"
        (staging / "bars").mkdir(parents=True)
        (staging / "bars" / "notes.csv").write_bytes(b"a\nb\nc\n")
        (staging / "bars" / "more.csv").write_bytes(b"x\ny\n")
        record = service.seal(staging, sealed_at=AT)

        (row,) = _rows(test_database_url, record.snapshot_hash)
        assert row[3] == 5  # 3 + 2, the manifest's total_rows

    def test_persisting_is_durable_across_services(
        self, service: SnapshotService, staged: Path, lake_root: Path, test_database_url: str
    ) -> None:
        # The point of the record over the manifest file: a *different*
        # process — modelled here as a service built from scratch — can
        # resolve a snapshot hash without opening the directory.
        record = service.seal(staged, sealed_at=AT)

        second = SnapshotService.from_env()
        (persisted,) = second.persisted(record.name)
        assert persisted.snapshot_hash == record.snapshot_hash
        assert persisted.exact_bytes == service.read_manifest(record.name).content_digest

    def test_an_idempotent_reseal_leaves_one_row(
        self, service: SnapshotService, staged: Path, test_database_url: str
    ) -> None:
        first = service.seal(staged, sealed_at=AT)
        second = service.seal(staged, sealed_at=AT)

        assert second.snapshot_hash == first.snapshot_hash
        assert len(_rows(test_database_url, first.snapshot_hash)) == 1

    def test_each_seal_in_an_extended_lake_is_its_own_row(
        self, service: SnapshotService, staged: Path, lake_root: Path
    ) -> None:
        # Feature 38's extension, seen from the record: the extension is a
        # new identity, so it is a new row, and the old row is untouched.
        first = service.seal(staged, sealed_at=AT)
        (staged / "bars" / "symbol=ETHUSDT" / "date=2026-09-01" / "part-1.parquet").write_bytes(
            b"extended"
        )
        second = service.seal(staged, sealed_at=AT)

        assert second.snapshot_hash != first.snapshot_hash
        records = service.manifest_records()
        assert {r.snapshot_hash for r in records} == {
            first.snapshot_hash,
            second.snapshot_hash,
        }


class TestAScoreCanNameTheExactBytes:
    """The clause that is easy to fake, and the tests that do not fake it."""

    def _same_shape_different_bytes(
        self, lake_root: Path
    ) -> tuple[SnapshotService, object, object]:
        """Seal two trees that agree on every column except the bytes.

        Both hold two files with identical *contents as a multiset* — the
        §4.2 fold hashes the sorted file hashes, so these two trees even
        share a ``snapshot_hash``-fold term — but the paths hold different
        bytes, which is exactly the distinction the spec's six columns
        cannot express. The universe differs only to keep the two identity
        hashes distinct; the row counts match exactly.
        """
        service = SnapshotService.from_env()
        staging = lake_root / "staging"

        (staging / "one").mkdir(parents=True)
        (staging / "one" / "a.txt").write_bytes(b"alpha\n")
        (staging / "one" / "b.txt").write_bytes(b"beta\n")
        first = service.seal(staging, sealed_at=AT, universe={"tag": "first"})

        (staging / "one" / "a.txt").write_bytes(b"beta\n")
        (staging / "one" / "b.txt").write_bytes(b"alpha\n")
        second = service.seal(staging, sealed_at=AT, universe={"tag": "second"})
        return service, first, second

    def test_the_specs_columns_alone_do_not_pin_bytes(self, lake_root: Path) -> None:
        service, first, second = self._same_shape_different_bytes(lake_root)

        (row_one,) = _rows(service.manifest_store.database_url, first.snapshot_hash)
        (row_two,) = _rows(service.manifest_store.database_url, second.snapshot_hash)
        # Same file count, same row count, same schema version: the spec's
        # summary columns agree, which is precisely why the identity needs
        # more than them.
        assert (row_one[2], row_one[3], row_one[5]) == (
            row_two[2],
            row_two[3],
            row_two[5],
        )

    def test_the_content_digest_separates_them(self, lake_root: Path) -> None:
        service, first, second = self._same_shape_different_bytes(lake_root)

        one = service.persisted(first.name)[0]
        two = service.persisted(second.name)[0]
        assert one.content_digest != two.content_digest

        # The same two trees folded over their hashes alone — the §4.2
        # term — are indistinguishable: the fold is a multiset and swaps
        # are invisible to it. That is the gap the record's digest closes.
        assert sorted(first.files.values()) == sorted(second.files.values())

    def test_the_recorded_digest_is_the_fold_over_named_bytes(
        self, service: SnapshotService, staged: Path
    ) -> None:
        record = service.seal(staged, sealed_at=AT)

        (persisted,) = service.persisted(record.name)
        assert persisted.content_digest == files_digest(record.files.items())
        assert persisted.content_digest == service.read_manifest(record.name).content_digest

    def test_a_swapped_entry_manifest_is_caught_by_the_recorded_digest(
        self, service: SnapshotService, staged: Path
    ) -> None:
        # The tamper the §4.2 hash cannot see: swap which path holds which
        # bytes *inside the manifest*, leaving every recorded sha256 one the
        # seal computed. The multiset is unchanged, so a record keyed by the
        # §4.2 hash alone would happily agree.
        record = service.seal(staged, sealed_at=AT)
        manifest_file = record.path / MANIFEST_NAME
        _unfreeze(manifest_file)
        payload = json.loads(manifest_file.read_text())
        path_a, path_b = sorted(payload["files"])[:2]
        payload["files"][path_a], payload["files"][path_b] = (
            payload["files"][path_b],
            payload["files"][path_a],
        )
        manifest_file.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        _refreeze(manifest_file)

        with pytest.raises(Exception, match="content_digest"):
            service.read_manifest(record.name)

    def test_the_record_names_bytes_the_directory_no_longer_holds(
        self, service: SnapshotService, staged: Path
    ) -> None:
        # Bytes tampered without touching the manifest: feature 36's own
        # check already catches this, and the *record* is the independent
        # second opinion — it was written from the seal, not from the tree,
        # so it names the bytes that were sealed even after they changed.
        record = service.seal(staged, sealed_at=AT)
        sealed_file = (
            record.path / "bars" / "symbol=BTCUSDT" / "date=2026-09-01" / "part-0.parquet"
        )
        _unfreeze(sealed_file)
        sealed_file.write_bytes(b"tampered after sealing")
        _refreeze(sealed_file)

        # The byte-level door refuses the snapshot, as feature 36 requires.
        with pytest.raises(Exception, match="is corrupt"):
            service.open(record.name)

        # And the recorded row still says what was sealed — the value a
        # score would have named, unchanged by the tamper.
        (persisted,) = service.manifest_store.rows_for(record.snapshot_hash)
        assert persisted.exact_bytes == files_digest(record.files.items())
        assert persisted.exact_bytes != files_digest(
            [("bars/symbol=BTCUSDT/date=2026-09-01/part-0.parquet", "0" * 64),
             *[(p, h) for p, h in record.files.items()
               if p != "bars/symbol=BTCUSDT/date=2026-09-01/part-0.parquet"]]
        )

    def test_an_untampered_snapshot_reports_no_findings(
        self, service: SnapshotService, staged: Path
    ) -> None:
        record = service.seal(staged, sealed_at=AT)
        assert service.record_findings(record.name) == ()

    def test_a_rewritten_manifest_is_caught_by_the_manifest_digest(
        self, service: SnapshotService, staged: Path
    ) -> None:
        # A wholesale rewrite: every recorded sha256 edited to match
        # tampered bytes, and the content_digest recomputed to agree. The
        # document is self-consistent and feature 36's on-disk check passes.
        # What it cannot do is change the row.
        record = service.seal(staged, sealed_at=AT)
        sealed_file = (
            record.path / "bars" / "symbol=BTCUSDT" / "date=2026-09-01" / "part-0.parquet"
        )
        _unfreeze(sealed_file)
        sealed_file.write_bytes(b"tampered after sealing")
        _refreeze(sealed_file)

        manifest_file = record.path / MANIFEST_NAME
        _unfreeze(manifest_file)
        payload = json.loads(manifest_file.read_text())
        relative = "bars/symbol=BTCUSDT/date=2026-09-01/part-0.parquet"
        payload["files"][relative]["sha256"] = hashlib.sha256(
            b"tampered after sealing"
        ).hexdigest()
        payload["content_digest"] = files_digest(
            (path, entry["sha256"]) for path, entry in payload["files"].items()
        )
        manifest_file.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        _refreeze(manifest_file)

        # Internally consistent, so the on-disk verification is satisfied...
        assert service.verify(record.name) is None
        # ...and the record still disagrees, in both directions at once.
        findings = service.record_findings(record.name)
        assert any("manifest_digest" in finding for finding in findings)
        assert any("content_digest" in finding for finding in findings)


class TestAMissedRowIsRepairedByReSealing:
    """The recovery path the ordering in ``_persist_manifest`` promises.

    The row is written *after* the rename, so a crash between the two — or
    a lake sealed before ``DATABASE_URL`` was pointed at it — leaves a
    sealed, verifiable snapshot with no row. The seal's own docstring says
    that state is "recoverable by re-sealing"; these tests hold it to that,
    for both ways of reaching it.
    """

    def test_a_seal_that_missed_its_row_is_repaired_by_resealing(
        self, lake_root: Path, staged: Path, test_database_url: str
    ) -> None:
        # The crash, simulated exactly: seal with no store configured (so
        # the publish happens and the row cannot), then bring a store into
        # being over the same lake and re-seal the same bytes.
        import os

        saved = os.environ.pop(DATABASE_URL_ENV, None)
        try:
            service = SnapshotService.from_env()
            record = service.seal(staged, sealed_at=AT)
        finally:
            os.environ[DATABASE_URL_ENV] = saved or test_database_url

        assert service.sealed() == [record.name]
        assert _rows(test_database_url, record.snapshot_hash) == []

        repaired = SnapshotService.from_env()
        assert repaired.unrecorded() == (record.name,)

        # The re-seal is idempotent for the directory and reparative for the
        # record: same name, same identity, and now a row.
        again = repaired.seal(staged, sealed_at=AT)
        assert again.name == record.name
        assert again.snapshot_hash == record.snapshot_hash
        assert len(_rows(test_database_url, record.snapshot_hash)) == 1
        assert repaired.unrecorded() == ()
        assert repaired.persisted(record.name)[0].exact_bytes == files_digest(
            again.files.items()
        )

    def test_the_repaired_row_matches_the_manifest_on_disk(
        self, lake_root: Path, staged: Path, test_database_url: str
    ) -> None:
        # The repair has to write the row from the bytes the snapshot
        # carries, not from a fresh build, or the two would be comparable
        # only by accident.
        import os

        saved = os.environ.pop(DATABASE_URL_ENV, None)
        try:
            record = SnapshotService.from_env().seal(staged, sealed_at=AT)
        finally:
            os.environ[DATABASE_URL_ENV] = saved or test_database_url

        service = SnapshotService.from_env()
        service.seal(staged, sealed_at=AT)

        # No findings: the re-asserted row agrees with the artifact in every
        # column, which is the strongest statement the pair can make.
        assert service.record_findings(record.name) == ()
        (persisted,) = service.persisted(record.name)
        assert persisted.content_digest == service.read_manifest(record.name).content_digest

    def test_resealing_a_recorded_snapshot_leaves_one_row(
        self, service: SnapshotService, staged: Path, test_database_url: str
    ) -> None:
        # The other side of the same coin: re-assertion must not accumulate
        # rows, or a schedule re-sealing a quiet lake would grow the table
        # without bound.
        record = service.seal(staged, sealed_at=AT)
        service.seal(staged, sealed_at=AT)
        service.seal(staged, sealed_at=AT)
        assert len(_rows(test_database_url, record.snapshot_hash)) == 1


class TestAPreManifestSnapshot:
    """A tree sealed before feature 31: no manifest, so no full hash, no row."""

    def _pre_manifest(self, lake_root: Path) -> str:
        name = "2026-09-02T00:00:00Z_bbbbbb"
        directory = lake_root / "snapshots" / name
        directory.mkdir()
        (directory / "bars.txt").write_bytes(b"pre-manifest bytes\n")
        return name

    def test_persisted_reports_an_absence_rather_than_crashing(
        self, service: SnapshotService, lake_root: Path
    ) -> None:
        # The row is keyed by a full hash only the manifest states, so this
        # snapshot can never have one. The honest answer is none — not a
        # bare FileNotFoundError from reading a file that was never written.
        name = self._pre_manifest(lake_root)
        assert service.persisted(name) == ()

    def test_record_findings_reports_nothing(
        self, service: SnapshotService, lake_root: Path
    ) -> None:
        name = self._pre_manifest(lake_root)
        assert service.record_findings(name) == ()

    def test_unrecorded_names_it(
        self, service: SnapshotService, lake_root: Path, staged: Path
    ) -> None:
        name = self._pre_manifest(lake_root)
        record = service.seal(staged, sealed_at=AT)

        assert service.unrecorded() == (name,)
        assert record.name not in service.unrecorded()

    def test_read_manifest_still_refuses_it_loudly(
        self, service: SnapshotService, lake_root: Path
    ) -> None:
        # The distinction the above four tests rest on: an *absence* in the
        # record paths, and a named refusal in the door that promises the
        # manifest itself.
        name = self._pre_manifest(lake_root)
        with pytest.raises(Exception, match="carries no"):
            service.read_manifest(name)


class TestTheRowIsWrittenOnceAndNeverEdited:
    def test_there_is_no_update_or_delete_surface(self) -> None:
        store = SnapshotManifestStore("sqlite:///:memory:")
        mutators = [
            name
            for name in dir(store)
            if not name.startswith("_")
            and callable(getattr(store, name))
            and any(
                verb in name
                for verb in ("update", "delete", "remove", "replace", "drop")
            )
        ]
        assert mutators == []

    def test_the_record_is_a_frozen_value(
        self, service: SnapshotService, staged: Path
    ) -> None:
        record = service.seal(staged, sealed_at=AT)
        (persisted,) = service.persisted(record.name)
        assert isinstance(persisted, SnapshotManifestRecord)
        with pytest.raises(Exception):
            persisted.row_count = 99  # type: ignore[misc]


class TestHonestAbsences:
    def test_a_lake_with_no_store_configured_still_seals(
        self, lake_root: Path, staged: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
        service = SnapshotService.from_env()
        assert service.manifest_store is None

        record = service.seal(staged, sealed_at=AT)
        assert record.files
        # No record was asked for, and the read paths say so rather than
        # pretending a row is missing.
        assert service.persisted(record.name) == ()
        assert service.manifest_records() == ()
        assert service.record_findings(record.name) == ()

    def test_an_unknown_total_is_still_recorded(
        self, service: SnapshotService, lake_root: Path, test_database_url: str
    ) -> None:
        # Feature 33 persists *each* sealed snapshot, and a snapshot whose
        # files include an opaque binary is a sealed snapshot like any
        # other. The manifest honestly records a null total, so the row
        # records a NULL total — the same answer, one store over. Neither
        # inventing a 0 nor skipping the row is acceptable: skipping would
        # leave the bytes no score could name, which is the feature's whole
        # point.
        staging = lake_root / "staging"
        (staging / "bars").mkdir(parents=True)
        (staging / "bars" / "blob.bin").write_bytes(bytes([0xFF, 0xFE, 0x00, 0x81]))
        (staging / "bars" / "notes.csv").write_bytes(b"a\nb\n")
        record = service.seal(staging, sealed_at=AT)

        assert service.read_manifest(record.name).total_rows is None
        (persisted,) = service.persisted(record.name)
        assert persisted.row_count is None
        assert persisted.snapshot_hash == record.snapshot_hash
        # The row still names the exact bytes — the part a score needs.
        assert persisted.exact_bytes == files_digest(record.files.items())
        assert persisted.file_count == 2
        # And it is a real row, not an absent one.
        assert len(_rows(test_database_url, record.snapshot_hash)) == 1
        assert service.unrecorded() == ()
        # The stored column really is NULL — distinguishable from a 0.
        assert _rows(test_database_url, record.snapshot_hash)[0][3] is None

    def test_an_unknown_total_agrees_with_its_artifact(
        self, service: SnapshotService, lake_root: Path, test_database_url: str
    ) -> None:
        # A NULL total must compare *clean* against the manifest's None,
        # not read as a disagreement — otherwise every opaque-binary
        # snapshot would look tampered.
        staging = lake_root / "staging"
        (staging / "bars").mkdir(parents=True)
        (staging / "bars" / "blob.bin").write_bytes(bytes([0xFF, 0xFE, 0x00, 0x81]))
        record = service.seal(staging, sealed_at=AT)

        assert service.record_findings(record.name) == ()

    def test_a_row_claiming_a_total_the_manifest_denies_is_a_finding(
        self, service: SnapshotService, lake_root: Path, test_database_url: str
    ) -> None:
        # The converse, and why the NULL has to be a real comparison rather
        # than a skipped one: a row that asserts an integer for a snapshot
        # whose manifest says the total is unknown *is* a disagreement.
        staging = lake_root / "staging"
        (staging / "bars").mkdir(parents=True)
        (staging / "bars" / "blob.bin").write_bytes(bytes([0xFF, 0xFE, 0x00, 0x81]))
        record = service.seal(staging, sealed_at=AT)

        url = service.manifest_store.database_url
        with sqlite3.connect(url.removeprefix("sqlite:///")) as connection:
            connection.execute(
                f"UPDATE {MANIFEST_TABLE} SET row_count = 0 WHERE snapshot_hash = ?",
                (record.snapshot_hash,),
            )
        findings = service.record_findings(record.name)
        assert any("row_count" in finding for finding in findings)

    def test_a_recorded_snapshot_is_not_reported_unrecorded(
        self, service: SnapshotService, staged: Path
    ) -> None:
        record = service.seal(staged, sealed_at=AT)
        assert service.unrecorded() == ()
        assert record.name not in service.unrecorded()

    def test_an_unrecorded_snapshot_reports_no_findings(
        self, service: SnapshotService, lake_root: Path, test_database_url: str
    ) -> None:
        # "No row" is not a disagreement — it is an absence, and
        # ``unrecorded`` is where it is reported. Reached here by sealing
        # with no store and then bringing one into being, which is the
        # crash-shaped case: the bytes are sealed, the row is missing, and
        # the two stores have nothing to disagree about.
        import os

        saved = os.environ.pop(DATABASE_URL_ENV, None)
        try:
            record = SnapshotService.from_env().seal(
                lake_root / "staging", sealed_at=AT
            )
        finally:
            os.environ[DATABASE_URL_ENV] = saved or test_database_url

        assert service.record_findings(record.name) == ()
        assert service.unrecorded() == (record.name,)

    def test_no_store_configured_means_every_snapshot_is_unrecorded(
        self, lake_root: Path, staged: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
        service = SnapshotService.from_env()
        record = service.seal(staged, sealed_at=AT)
        assert service.unrecorded() == (record.name,)


class TestAFailedWriteIsLoud:
    def test_a_broken_store_raises_carrying_the_published_snapshot(
        self, lake_root: Path, staged: Path, test_database_url: str
    ) -> None:
        # Point the store at a path that cannot be a database: a directory.
        blocked = lake_root / "blocked.db"
        blocked.mkdir()
        service = SnapshotService(
            lake_root,
            manifest_store=SnapshotManifestStore(f"sqlite:///{blocked}"),
        )

        with pytest.raises(SnapshotStoreError) as raised:
            service.seal(staged, sealed_at=AT)

        # The snapshot is published — the failure is the record, not the
        # bytes — and the error says which snapshot it is about.
        assert raised.value.record is not None
        assert raised.value.record.path.is_dir()
        assert service.sealed() == [raised.value.record.name]

    def test_a_non_sqlite_url_is_refused_by_name(self) -> None:
        store = SnapshotManifestStore("postgresql://localhost/nullius")
        with pytest.raises(SnapshotStoreError, match="sqlite"):
            store.hashes()


class TestManifestBackCompatibility:
    def test_a_manifest_without_the_content_digest_still_opens(
        self, service: SnapshotService, staged: Path
    ) -> None:
        # Trees sealed earlier in this same manifest version carry no
        # content_digest key. They must keep opening: the key is a
        # self-consistency claim, and a document that makes none cannot be
        # caught by it — but it must not be *refused* either.
        record = service.seal(staged, sealed_at=AT)
        manifest_file = record.path / MANIFEST_NAME
        _unfreeze(manifest_file)
        payload = json.loads(manifest_file.read_text())
        del payload["content_digest"]
        manifest_file.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        _refreeze(manifest_file)

        # The snapshot opens: the manifest still describes the bytes that
        # are there.
        assert service.open(record.name).name == record.name

    def test_a_recorded_digest_that_contradicts_the_entries_is_refused(
        self, service: SnapshotService, staged: Path
    ) -> None:
        record = service.seal(staged, sealed_at=AT)
        manifest_file = record.path / MANIFEST_NAME
        _unfreeze(manifest_file)
        payload = json.loads(manifest_file.read_text())
        payload["content_digest"] = "0" * 64
        manifest_file.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        _refreeze(manifest_file)

        with pytest.raises(Exception, match="disagrees with itself"):
            service.read_manifest(record.name)


class TestTheStoreItself:
    def test_resolve_treats_an_empty_url_as_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert SnapshotManifestStore.resolve({DATABASE_URL_ENV: "   "}) is None
        assert SnapshotManifestStore.resolve({}) is None
        assert SnapshotManifestStore.resolve({DATABASE_URL_ENV: "sqlite:///x.db"}) is not None

    def test_an_empty_url_is_refused_at_construction(self) -> None:
        with pytest.raises(SnapshotStoreError, match="non-empty"):
            SnapshotManifestStore("")

    def test_a_sqlite_url_with_a_host_is_refused(self) -> None:
        with pytest.raises(SnapshotStoreError, match="host"):
            SnapshotManifestStore("sqlite://remote/x.db").hashes()

    def test_the_schema_is_created_idempotently(
        self, tmp_path: Path
    ) -> None:
        url = f"sqlite:///{tmp_path / 'fresh.db'}"
        first = SnapshotManifestStore(url)
        assert first.hashes() == []
        # A second store over the same file takes the same path.
        assert SnapshotManifestStore(url).hashes() == []

    def test_a_row_that_cannot_be_read_is_refused(
        self, service: SnapshotService, staged: Path
    ) -> None:
        record = service.seal(staged, sealed_at=AT)
        url = service.manifest_store.database_url
        path = url.removeprefix("sqlite:///")
        with sqlite3.connect(path) as connection:
            connection.execute(
                f"UPDATE {MANIFEST_TABLE} SET sealed_at = 'not-a-time' "
                "WHERE snapshot_hash = ?",
                (record.snapshot_hash,),
            )
        with pytest.raises(Exception, match="canonical"):
            service.manifest_store.rows_for(record.snapshot_hash)
