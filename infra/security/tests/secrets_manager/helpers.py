"""A throwaway git repository for feature 151's committed-file check.

The whole of feature 151's "committed" lives in version control, so the suite
needs a repository it can commit into and point the store at. This is a plain
helper — imported directly, the way a sibling suite imports a sibling module —
so a test builds one with ``GitRepo(root)`` and drives it with :meth:`write`
and :meth:`commit`. The git calls carry an inline identity so the suite needs
no global config, and commit signing is off so a deployment's hooks cannot
block the fixture.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


class GitRepo:
    """A throwaway git repository the committed-file check is exercised against."""

    def __init__(self, root: Path) -> None:
        self.root = root
        subprocess.run(
            ["git", "init", "-q"], cwd=str(root), check=True, capture_output=True
        )

    def write(self, name: str, content: str) -> Path:
        """Write ``content`` to ``root / name`` — staged only when committed."""
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def commit(self, message: str = "commit") -> None:
        """Stage everything and commit — the moment files become committed."""
        subprocess.run(["git", "add", "-A"], cwd=str(self.root), check=True, capture_output=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.email=test@example.com",
                "-c",
                "user.name=Test",
                "-c",
                "commit.gpgsign=false",
                "commit",
                "-q",
                "-m",
                message,
            ],
            cwd=str(self.root),
            check=True,
            capture_output=True,
        )

    def committed(self) -> set[str]:
        """The tracked paths, as the store's check would see them."""
        listing = subprocess.run(
            ["git", "ls-files", "--", str(self.root)],
            cwd=str(self.root),
            check=True,
            capture_output=True,
            text=True,
        )
        return {line.strip() for line in listing.stdout.splitlines() if line.strip()}
