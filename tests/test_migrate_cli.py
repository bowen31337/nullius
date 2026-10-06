"""``python -m app.migrate`` -- the runner for migrations/versions/0*.py now
that ``./run.sh migrate`` no longer shells out to Alembic (the workspace has
no alembic.ini and never adopted it).

This suite drives :func:`app.migrate.main` directly over a throwaway,
per-test SQLite file -- never a real subprocess, the same discipline
:mod:`canary.run`'s own CLI suite uses -- except for the raising-migration
case, which needs a tmp copy of the real tree with one file's ``apply``
broken, so it points ``versions_dir`` at that copy instead of the real one.

One test per claim the bug's expected behaviour makes:

* a fresh database reaches head, printing one JSON line per file plus a
  final ``{"head": ...}`` line, and the tables the chain creates exist.
* running it again exits 0 and changes nothing (each file's own ``apply()``
  is idempotent).
* a missing ``DATABASE_URL`` exits 2, naming the variable, one line, no
  traceback.
* a file whose ``apply()`` raises exits 1, naming the revision and the
  error, one line, no traceback -- and the migrations before it stay
  applied.

No test opens a network connection or writes outside a pytest temporary
directory, and none holds state at module scope, so the suite passes under
pytest-xdist.
"""

from __future__ import annotations

import io
import json
import shutil
import sqlite3
from contextlib import closing, redirect_stderr
from pathlib import Path

from app.migrate import (
    DATABASE_URL_ENV,
    EXIT_CONFIG,
    EXIT_MIGRATION_FAILED,
    EXIT_OK,
    VERSIONS_DIR,
    discover_chain,
    main,
)


def _url(tmp_path: Path, name: str = "migrate.db") -> str:
    return f"sqlite:///{tmp_path / name}"


def _path(url: str) -> Path:
    return Path(url.removeprefix("sqlite:///"))


def _table_exists(url: str, table: str) -> bool:
    path = _path(url)
    if not path.exists():
        return False
    with closing(sqlite3.connect(path)) as connection:
        row = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
    return row is not None


def _expected_chain():
    return discover_chain(VERSIONS_DIR)


def test_fresh_database_reaches_head(tmp_path: Path) -> None:
    url = _url(tmp_path)
    lines: list[str] = []

    exit_code = main([], env={DATABASE_URL_ENV: url}, emit=lines.append)

    assert exit_code == EXIT_OK
    expected = _expected_chain()
    *per_file, last = (json.loads(line) for line in lines)
    assert len(per_file) == len(expected)
    for payload, module in zip(per_file, expected):
        assert payload["revision"] == module.REVISION
        assert payload["statements"] >= 1
    assert last == {"head": expected[-1].REVISION}

    for module in expected:
        if module.TABLES:  # some migrations only ALTER an existing table
            assert _table_exists(url, module.TABLES[0]), module.REVISION


def test_rerun_is_idempotent(tmp_path: Path) -> None:
    url = _url(tmp_path)
    first = main([], env={DATABASE_URL_ENV: url}, emit=lambda _line: None)
    assert first == EXIT_OK

    second_lines: list[str] = []
    second = main([], env={DATABASE_URL_ENV: url}, emit=second_lines.append)

    assert second == EXIT_OK
    head_line = json.loads(second_lines[-1])
    assert head_line == {"head": _expected_chain()[-1].REVISION}


def test_missing_database_url_exits_2_naming_it() -> None:
    stderr = io.StringIO()
    with redirect_stderr(stderr):
        exit_code = main([], env={}, emit=lambda _line: None)

    assert exit_code == EXIT_CONFIG
    message = stderr.getvalue()
    assert DATABASE_URL_ENV in message
    assert "Traceback" not in message
    assert message.count("\n") == 1


def test_a_raising_migration_exits_1_naming_revision_and_stops_cleanly(
    tmp_path: Path,
) -> None:
    broken_versions = tmp_path / "versions"
    shutil.copytree(VERSIONS_DIR, broken_versions)
    chain = discover_chain(broken_versions)
    assert len(chain) >= 2, "need at least one predecessor to prove partial apply"

    broken = chain[len(chain) // 2]
    earlier = chain[: chain.index(broken)]
    predecessor = next(m for m in reversed(earlier) if m.TABLES)
    broken_file = broken_versions / f"{broken.REVISION}.py"
    with broken_file.open("a") as handle:
        handle.write(
            "\n\n"
            "def apply(database_url=None):  # overrides the real apply() above\n"
            "    raise RuntimeError('boom: forced failure for test')\n"
        )

    url = _url(tmp_path)
    lines: list[str] = []
    stderr = io.StringIO()
    with redirect_stderr(stderr):
        exit_code = main(
            [],
            env={DATABASE_URL_ENV: url},
            emit=lines.append,
            versions_dir=broken_versions,
        )

    assert exit_code == EXIT_MIGRATION_FAILED
    message = stderr.getvalue()
    assert broken.REVISION in message
    assert "boom: forced failure for test" in message
    assert "Traceback" not in message
    assert message.count("\n") == 1

    # Migrations before the broken one are each their own committed unit, so
    # they stay applied; nothing after it (including the head line) ran.
    assert _table_exists(url, predecessor.TABLES[0])
    applied_revisions = {json.loads(line)["revision"] for line in lines}
    assert broken.REVISION not in applied_revisions
    assert all("head" not in json.loads(line) for line in lines)
