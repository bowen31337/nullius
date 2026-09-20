"""Feature 167: the committed artifact — the ceiling the law screens against.

The step this file's subject makes checkable: *"importing anything outside
the configured allowlist"* is only a refusable condition if the deployment
has a written-down statement of what *inside* means.  The committed document
(:data:`~sandbox.COMMITTED_IMPORTS_ALLOWLIST`) is that statement — the
ceiling the deployment runs with before anyone writes a stanza — and the
tests here read it the way an operator or a CI check would: compiled through
the same refusal as any change to it, satisfying §12's determinism row by
what it lists (and, for ``time``, by what it pointedly does not), and
covering the payload stack §5.1's contract actually executes on.
"""

from __future__ import annotations

import json

from _documents import COMMITTED_ALLOWLIST_TERMS
from sandbox import (
    COMMITTED_IMPORTS_ALLOWLIST,
    IMPORTS_POLICY_KIND,
    committed_imports_allowlist,
    load_imports_allowlist,
)


class TestTheArtifact:
    """The document on disk, as facts rather than prose."""

    def test_the_artifact_exists_beside_the_module(self) -> None:
        """The committed ceiling ships with the law that checks it, so a
        checkout cannot hold one without the other."""
        assert COMMITTED_IMPORTS_ALLOWLIST.exists()

    def test_the_artifact_declares_its_kind(self) -> None:
        """It says what it is — the marker the compile holds it to, so a
        stray JSON file carrying an ``allow`` key cannot be read as this
        configuration."""
        with COMMITTED_IMPORTS_ALLOWLIST.open("r", encoding="utf-8") as handle:
            document = json.load(handle)
        assert document["policy"] == IMPORTS_POLICY_KIND

    def test_the_artifacts_terms_are_exactly_the_committed_ceiling(self) -> None:
        """The list is pinned exactly rather than by membership, so a term
        arriving unnoticed fails here — the same property the component
        test pins the member's component list for.  A widened ceiling is a
        deployment decision, and it happens in this file, in review, or
        not at all."""
        with COMMITTED_IMPORTS_ALLOWLIST.open("r", encoding="utf-8") as handle:
            document = json.load(handle)
        assert tuple(document["allow"]) == COMMITTED_ALLOWLIST_TERMS


class TestTheCommittedCeiling:
    """What the compiled artifact holds, and §12's stake in it."""

    def test_the_committed_ceiling_compiles_from_disk(self) -> None:
        """The loader's whole job, proven: read the committed file, refuse
        nothing about it, hand back a ceiling."""
        assert committed_imports_allowlist().kind == IMPORTS_POLICY_KIND

    def test_the_wall_clock_module_is_absent_by_construction(self) -> None:
        """§12's determinism row names ``time`` first, and it has no
        sanctioned spelling — every use of it is a wall-clock read — so the
        committed ceiling lists nothing for it and a submission importing
        it is refused by the ceiling itself."""
        ceiling = committed_imports_allowlist()
        assert "time" not in ceiling.terms()
        assert ceiling.covers("time") is False
        assert ceiling.covers("time.monotonic") is False

    def test_the_sanctioned_random_and_datetime_spellings_are_admitted(self) -> None:
        """Both modules stay importable because the deterministic spellings
        need them: a datetime built from explicit arguments is a value, and
        the seeded RNG of §12's next row is ``random.Random(seed)``.  The
        *call-level* floor (``datetime.now``, unseeded draws) is feature
        139's law at the search seam; this seam's law is the ceiling, and
        the two compose rather than duplicate."""
        ceiling = committed_imports_allowlist()
        assert ceiling.covers("random") is True
        assert ceiling.covers("random.Random") is True
        assert ceiling.covers("datetime") is True
        assert ceiling.covers("datetime.datetime") is True

    def test_the_payload_stack_is_admitted(self) -> None:
        """§5.1's contract is polars-native (``bars()`` returns
        ``pl.DataFrame``, ``signal()`` returns ``pl.Series``), the numeric
        layer sits beneath it, and the window arrives as Arrow IPC — a
        ceiling that refused them would refuse every signal the loop can
        legally write."""
        ceiling = committed_imports_allowlist()
        for term in ("polars", "polars.DataFrame", "numpy", "numpy.linalg", "pyarrow"):
            assert ceiling.covers(term), term

    def test_the_world_the_box_refuses_is_absent(self) -> None:
        """§5.2's control table gives the box no network and no mounts, so
        the modules that touch that world are not in the ceiling — a
        submission importing them is the feature's headline refusal."""
        ceiling = committed_imports_allowlist()
        for term in ("os", "sys", "socket", "subprocess", "pathlib", "shutil"):
            assert not ceiling.covers(term), term

    def test_the_loader_and_the_committed_shortcut_agree(self) -> None:
        """``committed_imports_allowlist`` is not privileged: it goes
        through the same read-and-compile as any other path, so a drift in
        the file is refused on both."""
        assert load_imports_allowlist(COMMITTED_IMPORTS_ALLOWLIST).terms() == (
            committed_imports_allowlist().terms()
        )
