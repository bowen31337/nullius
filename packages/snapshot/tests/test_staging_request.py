"""Feature 35 — the evaluator's request for staging is refused, and says why.

app_spec.xml feature 35 — *"System rejects an evaluator request naming a
staging path, because staging is never on the evaluator mount path"* — is the
read-side twin of feature 28 (*"ingest output goes append-only into a staging
area that never appears on the evaluator mount path"*). Feature 28 keeps
staging off the mount by *layout*; this feature keeps it off by *refusal*: an
evaluator that asks for ``staging`` is told, in contract terms, that staging
is not something it may open.

The mount of feature 34 is the evaluator's door, and it is built on
:meth:`SnapshotService.open`, so the refusal lives there — the single seam
every read path (``open``, ``mount``, ``mounted``) goes through. The refusal
is a :class:`SnapshotStagingRequestError`, a :class:`SnapshotNotFoundError`
specialised to name staging and point the evaluator at the sealed snapshots
it *may* open. Three things are tested, because a refusal that satisfied only
two of them would be a different feature:

* **it is refused** — a request naming the staging area never becomes a path
  and never opens; it raises;
* **it names staging** — the error states the contract: staging is the ingest
  workers' writable area, never on the evaluator mount path, and the sealed
  snapshots are what to open instead;
* **it is a miss of the right kind** — the error is a
  :class:`SnapshotNotFoundError` (and so a :class:`SnapshotError`), so a
  caller catching either vocabulary handles it, while a malformed name and a
  genuine miss are still told apart.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from snapshot import (
    SnapshotError,
    SnapshotNameError,
    SnapshotNotFoundError,
    SnapshotService,
    SnapshotStagingRequestError,
)

AT = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
HASH = "a3f91c" + "0" * 58
NAME = "2026-09-01T00:00:00Z_a3f91c"


@pytest.fixture
def sealed(service: SnapshotService, lake_root: Path) -> Path:
    """A sealed snapshot, so the lake has something the evaluator may open."""
    staging = lake_root / "staging"
    (staging / "bars").mkdir()
    (staging / "bars" / "part-0.parquet").write_bytes(b"payload")
    return service.seal(staging, sealed_at=AT, snapshot_hash=HASH).path


class TestARequestNamingStagingIsRefused:
    @pytest.mark.parametrize(
        "request_",
        [
            "staging",
            "staging/part.parquet",
            "staging/bars/symbol=BTCUSDT/date=2026-09-01/part-0.parquet",
        ],
    )
    def test_a_staging_request_raises(
        self, service: SnapshotService, request_: str
    ) -> None:
        with pytest.raises(SnapshotStagingRequestError):
            service.open(request_)

    def test_the_staging_request_never_becomes_a_path(
        self, service: SnapshotService, lake_root: Path
    ) -> None:
        # The strongest statement: opening staging must not return a handle
        # that points at the writable area, whatever the request's shape.
        with pytest.raises(SnapshotStagingRequestError):
            ref = service.open("staging")
            assert not Path(ref.path).is_relative_to(lake_root / "staging")

    def test_mounting_staging_is_refused_the_same_way(
        self, service: SnapshotService
    ) -> None:
        # The mount is the evaluator's door, so the refusal must hold there
        # too — the mount goes through open, and open is where the refusal is.
        with pytest.raises(SnapshotStagingRequestError):
            service.mount("staging")

    def test_a_staging_request_does_not_read_the_staging_bytes(
        self, service: SnapshotService, lake_root: Path
    ) -> None:
        # A staging file is present with real bytes; the refusal must not have
        # reached them. If open had resolved and read the staging tree, the
        # feature would be the opposite of what it claims.
        (lake_root / "staging" / "secret.parquet").write_bytes(b"staging-only")
        with pytest.raises(SnapshotStagingRequestError):
            service.open("staging/secret.parquet")
        assert (lake_root / "staging" / "secret.parquet").read_bytes() == b"staging-only"


class TestTheRefusalNamesStaging:
    def test_the_message_states_the_contract(self, service: SnapshotService) -> None:
        with pytest.raises(SnapshotStagingRequestError) as caught:
            service.open("staging")
        message = str(caught.value)
        assert "staging" in message  # it names the area
        assert "never on the evaluator mount path" in message  # ... and why
        assert "writable area" in message  # ... and what staging is
        assert "sealed" in message  # ... and that sealed snapshots are the door
        assert "SnapshotService.sealed" in message  # ... and how to open one instead

    def test_the_message_names_the_staging_path(self, service: SnapshotService) -> None:
        # An operator reading the error needs the concrete path, not just the
        # word "staging", to tell a staging request from a typo.
        with pytest.raises(SnapshotStagingRequestError) as caught:
            service.open("staging/bars/part-0.parquet")
        assert str(service.staging_root) in str(caught.value)


class TestTheStagingRequestIsAMissOfTheRightKind:
    def test_it_is_a_snapshot_not_found_error(self) -> None:
        # A staging request is a request that names nothing the evaluator may
        # open, so it is a miss — but a miss *for a reason*. Specialising on
        # SnapshotNotFoundError keeps both catchable: ``except
        # SnapshotNotFoundError`` and ``except SnapshotError`` both work.
        assert issubclass(SnapshotStagingRequestError, SnapshotNotFoundError)
        assert issubclass(SnapshotStagingRequestError, SnapshotError)

    def test_it_is_caught_as_a_not_found_error(self, service: SnapshotService) -> None:
        with pytest.raises(SnapshotNotFoundError):
            service.open("staging")

    def test_it_is_caught_as_a_snapshot_error(self, service: SnapshotService) -> None:
        with pytest.raises(SnapshotError):
            service.open("staging")


class TestStagingIsToldApartFromOtherMisses:
    def test_a_malformed_name_is_a_name_error_not_a_staging_error(
        self, service: SnapshotService
    ) -> None:
        # ``../staging`` never reaches staging — the strict parser refuses it
        # as a malformed name first. A staging refusal must not swallow the
        # naming contract: traversal dies as a SnapshotNameError.
        with pytest.raises(SnapshotNameError):
            service.open("../staging")

    def test_a_genuine_miss_is_a_plain_not_found_error(
        self, service: SnapshotService
    ) -> None:
        # A canonical name that names nothing is a miss, and it is not a
        # staging request — the two are distinct refusals with distinct
        # messages.
        with pytest.raises(SnapshotNotFoundError) as caught:
            service.open("2026-09-01T00:00:00Z_000000")
        assert not isinstance(caught.value, SnapshotStagingRequestError)
        assert "no sealed snapshot" in str(caught.value)

    def test_a_sealed_snapshot_opens(self, service: SnapshotService, sealed: Path) -> None:
        # The contrast that gives the refusal meaning: the sealed snapshot the
        # staging request was steered toward opens normally.
        ref = service.open(NAME)
        assert ref.path == sealed


class TestStagingDetectionIsByContainment:
    def test_a_request_reaching_staging_through_any_spelling_is_caught(
        self, service: SnapshotService, lake_root: Path
    ) -> None:
        # Detection is by resolved containment, not string match, so a request
        # that reaches the staging area through a redundant ``./`` still names
        # staging — the mount-path contract does not depend on the caller's
        # spelling.
        with pytest.raises(SnapshotStagingRequestError):
            service.open("staging/./bars/part-0.parquet")

    def test_a_canonical_request_is_never_mistaken_for_staging(
        self, service: SnapshotService, sealed: Path
    ) -> None:
        # The containment check must never shadow a genuine snapshot request:
        # a canonical name resolves under snapshots/, never staging.
        ref = service.open(NAME)
        assert ref.path == sealed
        assert not Path(ref.path).is_relative_to(service.staging_root)
