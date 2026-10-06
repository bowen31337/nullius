"""Seal a lake's staging area from the command line -- ``python -m snapshot.seal``.

``additions_spec_real_campaign_path.xml``, "Market Data to Sealed Snapshot"
category, feature 3: *System seals the staging area with* ``python -m
snapshot.seal --lake LAKE [--sealed-at ISO]`` *and displays one JSON line
with the snapshot name, path, full hash, file count and row count.* The
sealing machinery already exists (:class:`~snapshot.SnapshotService`,
:func:`~snapshot.seal_snapshot`); nothing before this module could be run by
an operator or a cron job pointed at a lake directory. This is that door,
and nothing more -- it resolves ``--lake`` and ``<LAKE>/universe.json``,
then hands the rest to the service.

**Three decisions this module adds on top of the service it wraps:**

* **Staging may hold nothing but ``bars/`` partitions.** ``bars/`` is the
  only partition kind any producer in this workspace writes today (the
  market-data ingest of this same category, feature 1/2); the further kinds
  docs/nullius-tech-architecture.md §4.2 names for the lake's eventual shape
  (``trades/``, ``bookfeat/``, ``borrow/``, ``exchangeinfo/``) have no
  writer yet. :class:`~snapshot.SnapshotService` itself seals whatever a
  staging tree holds -- that breadth is right for the library, which also
  serves future partition kinds and hand-built test fixtures -- but *this*
  command is the one an operator runs to turn today's market-data staging
  into what the evaluator reads, so it refuses here, naming the first stray
  path it finds, rather than silently sealing debris into an immutable
  directory.
* **An existing target name is always refused, not replayed.** The service
  itself treats a re-seal of byte-identical content under an existing name
  as idempotent (a crashed schedule's retry). This command does not reach
  that nuance: it checks the candidate name for existence *before* calling
  the service, and refuses unconditionally when it is taken. An operator
  running this command twice at the same ``--sealed-at`` over unmoved
  staging is a case worth looking at, not a silent no-op the command should
  paper over.
* **``DATABASE_URL`` is optional, not required.** Unlike this workspace's
  other operator CLIs (``bootstrap.fill``, ``canary.run``), which refuse
  outright with no store configured, this command mirrors
  :class:`~snapshot.SnapshotService`'s own stance: a lake with no
  ``DATABASE_URL`` still seals, because the filesystem records (the sealed
  directory and its ``MANIFEST.json``) are complete on their own. The
  absence is noted on stderr -- *"allowed and says so"* -- rather than
  silenced or refused.

``<LAKE>/universe.json`` is read from beside ``staging/``, never from
inside it, so "keeps it out of the sealed tree" is a property of which path
is read, not a filter applied afterwards -- it was never part of what the
seal walks to begin with. Its content becomes the seal's ``universe=``
argument unchanged; a value that is not a JSON object is left to
:func:`~snapshot.snapshot_digest`'s own validation to refuse, so there is
exactly one place in this workspace that states what a universe definition
must look like.

**Exit codes**, this category's own: 0 once the snapshot is sealed and the
line is printed, whether or not a ``snapshot_manifest`` row was recorded; 1
for every refusal -- a stray path outside ``bars/``, a target name already
sealed, or any other :class:`~snapshot.SnapshotError` the seal raises (a
missing staging directory, an invalid ``universe.json``, a configured
``DATABASE_URL`` whose write fails) -- printed to stderr with no traceback,
exactly as :func:`~snapshot.seal_snapshot` would raise it.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from ._content import walk_content
from ._errors import SnapshotAlreadySealedError, SnapshotError
from ._identity import snapshot_digest
from ._manifest_store import DATABASE_URL_ENV, MANIFEST_TABLE, SnapshotManifestStore
from ._naming import snapshot_name
from ._service import SnapshotService

__all__ = [
    "ALREADY_SEALED_CODE",
    "EXIT_OK",
    "EXIT_REFUSED",
    "STRAY_PATH_CODE",
    "UNIVERSE_FILENAME",
    "SealResult",
    "main",
    "seal_lake",
]

#: This module's own refusal when staging holds something other than a
#: ``bars/`` partition -- never a collaborator's, which already names its
#: own contract (``SnapshotAlreadySealedError`` and friends).
STRAY_PATH_CODE = "snapshot_seal_stray_path"

#: This module's own refusal when the candidate target name is already
#: sealed -- checked before the service is ever asked to seal anything.
ALREADY_SEALED_CODE = "snapshot_seal_already_sealed"

#: The one file this command reads beside ``staging/``, never inside it.
UNIVERSE_FILENAME = "universe.json"

#: Sealed, whether or not a ``snapshot_manifest`` row was recorded.
EXIT_OK = 0
#: A refusal: a stray path outside ``bars/``, a name already sealed, or any
#: other :class:`~snapshot.SnapshotError` the seal raises.
EXIT_REFUSED = 1


@dataclass(frozen=True)
class SealResult:
    """The one JSON line this command prints."""

    #: The sealed directory's canonical name, ``<sealed_at>_<hash prefix>``.
    name: str
    #: The sealed directory's path.
    path: Path
    #: The full 64-character snapshot hash the name's prefix abbreviates.
    snapshot_hash: str
    #: How many content files the snapshot holds.
    file_count: int
    #: The total rows across those files, or ``None`` when some file's
    #: format carries no row concept (the manifest's own honest unknown).
    row_count: int | None

    def to_payload(self) -> dict[str, object]:
        """The result as one JSON line, field order matching the feature's
        own sentence: name, path, full hash, file count, row count."""
        return {
            "name": self.name,
            "path": str(self.path),
            "snapshot_hash": self.snapshot_hash,
            "file_count": self.file_count,
            "row_count": self.row_count,
        }


def _read_universe(lake_root: Path) -> object:
    """``<LAKE>/universe.json``, parsed -- or ``None`` when there is none.

    Read from beside ``staging/``, so it is never among the paths
    :func:`~snapshot._content.walk_content` sees and never reaches the
    sealed tree -- the exclusion is a consequence of which path this reads,
    not a filter applied afterwards. An unreadable file or malformed JSON is
    refused here, by name, rather than surfacing later as a bare decode
    error; a value that parses but is not a JSON object (a list, a string)
    is passed through unchanged, so :func:`~snapshot.snapshot_digest`'s own
    ``validate_universe`` door is the one place that states what a universe
    definition must look like.
    """
    path = lake_root / UNIVERSE_FILENAME
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SnapshotError(f"{path} could not be read: {exc}") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise SnapshotError(f"{path} is not valid JSON: {exc}") from exc


def _first_stray_path(files: Mapping[str, str]) -> str | None:
    """The first staged path outside ``bars/``, sorted -- or ``None``.

    Sorted so the same staged tree always names the same stray path, run to
    run, rather than depending on dict iteration order.
    """
    for candidate in sorted(files):
        if not candidate.startswith("bars/"):
            return candidate
    return None


def seal_lake(
    lake: str | os.PathLike[str],
    *,
    sealed_at: str | None = None,
    env: Mapping[str, str] | None = None,
) -> tuple[SealResult, bool]:
    """Seal ``<lake>/staging`` and return the result and whether it was recorded.

    ``sealed_at`` is an optional ISO 8601 string (``None`` means now, the
    same default :func:`~snapshot.seal_snapshot` applies). ``env`` resolves
    ``DATABASE_URL`` (the process environment when ``None``); the lake
    itself is always ``lake``, named explicitly rather than through
    ``LAKE_ROOT`` -- this command's whole argument, not an environment
    default.

    Refuses with :class:`~snapshot.SnapshotError` (see the module docstring
    for the two refusals this module adds) before anything is written, and
    propagates every refusal :meth:`~snapshot.SnapshotService.seal` or
    :meth:`~snapshot.SnapshotService.read_manifest` raises unchanged.

    Returns the printed result paired with whether a ``snapshot_manifest``
    row was recorded for it -- ``True`` only when ``DATABASE_URL`` named a
    store, since a configured store that failed to write would already have
    raised rather than let this function return.
    """
    lake_root = Path(lake).expanduser()
    staging_root = lake_root / "staging"
    universe = _read_universe(lake_root)

    files = walk_content(staging_root)
    stray = _first_stray_path(files)
    if stray is not None:
        raise SnapshotError(
            f"{STRAY_PATH_CODE}: staging at {staging_root} holds {stray!r}, "
            "which is not a bars/ partition; a sealed snapshot holds only "
            "what the evaluator reads -- move or remove it before sealing"
        )

    full_hash = snapshot_digest(files, universe=universe)
    name = snapshot_name(sealed_at, full_hash)

    source = os.environ if env is None else env
    store = SnapshotManifestStore.resolve(source)
    service = SnapshotService(lake_root, manifest_store=store)

    target = service.snapshots_root / name
    if target.exists():
        raise SnapshotAlreadySealedError(
            f"{ALREADY_SEALED_CODE}: {name!r} is already sealed at {target}; "
            "this command seals the current staging content under a name "
            "nothing has used yet -- point --sealed-at elsewhere, or confirm "
            "the staged content really is already sealed"
        )

    record = service.seal(
        staging_root, sealed_at=sealed_at, snapshot_hash=full_hash, universe=universe
    )
    manifest = service.read_manifest(record.name)
    result = SealResult(
        name=record.name,
        path=record.path,
        snapshot_hash=record.snapshot_hash,
        file_count=manifest.file_count,
        row_count=manifest.total_rows,
    )
    return result, store is not None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m snapshot.seal",
        description=(
            "Seal a lake's staging area into an immutable snapshot, and "
            "print its name, path, full hash, file count and row count as "
            "one JSON line."
        ),
    )
    parser.add_argument(
        "--lake",
        required=True,
        metavar="LAKE",
        help="the lake root holding staging/ and, optionally, universe.json",
    )
    parser.add_argument(
        "--sealed-at",
        dest="sealed_at",
        default=None,
        metavar="ISO",
        help="the sealing instant, ISO 8601 with a UTC offset (default: now)",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    emit: Callable[[str], object] = print,
) -> int:
    """``python -m snapshot.seal --lake LAKE [--sealed-at ISO]``.

    Seals ``<LAKE>/staging`` (:func:`seal_lake`) and prints one JSON line
    through ``emit``. A refusal -- this module's own (a stray path, an
    already-sealed name) or a collaborator's (``SnapshotError`` and its
    subclasses) -- is printed to stderr verbatim, with no traceback, and
    answered :data:`EXIT_REFUSED`; nothing is written in that case.

    ``DATABASE_URL`` is read from ``env`` (the process environment when
    ``None``). It is optional for this command: when it names no store, the
    seal still happens and this prints one line to stderr saying so, rather
    than refusing -- the filesystem records are complete without it.

    ``env`` and ``emit`` are this command's seams, taken the way every
    operator CLI in this workspace takes them (see ``canary.run``,
    ``bootstrap.fill``): ``env`` is where ``DATABASE_URL`` is read from, and
    ``emit`` is what the one JSON line is printed with -- so the suite
    drives this command in-process, with no subprocess and no real
    environment.
    """
    arguments = _build_parser().parse_args(argv)
    source = os.environ if env is None else env

    try:
        result, recorded = seal_lake(
            arguments.lake, sealed_at=arguments.sealed_at, env=source
        )
    except SnapshotError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_REFUSED

    if not recorded:
        print(
            f"{DATABASE_URL_ENV} is not set; no {MANIFEST_TABLE} row was "
            "recorded for this seal",
            file=sys.stderr,
        )
    emit(json.dumps(result.to_payload()))
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover - the module's own door
    raise SystemExit(main())
