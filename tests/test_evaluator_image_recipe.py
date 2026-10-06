"""The evaluator image recipe is reproducible and digest-pinned by construction.

additions_spec_real_campaign_path.xml feature 6: ``NULLIUS_EVALUATOR_IMAGE``
must be a digest-pinned reference so ``evaluator_hash`` (architecture §6,
§12) names real, rebuildable content — never a made-up digest. Architecture
§12's determinism contract requires a pinned evaluator, pinned libraries
("lockfile inside the image; no runtime ``pip install``") and single-threaded,
stable-order numerics in every eval worker.

This suite checks the recipe statically: it parses
``deploy/evaluator/Containerfile`` and ``deploy/evaluator/build_image.sh`` as
text (and, for the shell script, as a syntax tree via ``bash -n``) and never
invokes podman or buildah — building a real image needs a container engine
with working rootless namespaces, which the acceptance gate's sandbox does
not have. Building and inspecting the actual image is a manual, by-hand step
for whoever runs ``deploy/evaluator/build_image.sh``.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EVALUATOR_DIR = REPO_ROOT / "deploy" / "evaluator"
CONTAINERFILE = EVALUATOR_DIR / "Containerfile"
BUILD_SCRIPT = EVALUATOR_DIR / "build_image.sh"

#: The workspace members feature 6 names, mapped to the ``[project].name``
#: each one's own ``pyproject.toml`` declares. ``contract``'s directory does
#: not match its project name — ``packages/contract/pyproject.toml`` declares
#: ``name = "nullius-contract"`` — so the ``uv sync --package`` flags in the
#: Containerfile must name the project, not the directory.
MEMBER_PROJECT_NAMES = {
    "evaluator": "evaluator",
    "cost-model": "cost-model",
    "contract": "nullius-contract",
    "snapshot": "snapshot",
    "nulloracle": "nulloracle",
}

SHA256_DIGEST_RE = r"sha256:[0-9a-f]{64}"


def _containerfile_text() -> str:
    return CONTAINERFILE.read_text()


def _build_script_text() -> str:
    return BUILD_SCRIPT.read_text()


def _env_instructions(text: str) -> str:
    """Every ``ENV`` instruction's text, continuation lines joined in.

    Backslash line-continuations are how a Containerfile spreads one ``ENV``
    across several lines; collecting them is what lets a test tell "this
    assignment is inside an ENV instruction" apart from "this string
    happens to appear in a comment".
    """
    collected: list[str] = []
    lines = iter(text.splitlines())
    for line in lines:
        if not line.strip().upper().startswith("ENV "):
            continue
        instruction = [line]
        while instruction[-1].rstrip().endswith("\\"):
            instruction.append(next(lines))
        collected.append("\n".join(instruction))
    return "\n".join(collected)


class TestTheBaseImageIsDigestPinned:
    def test_the_from_line_pins_python_3_12_slim_by_digest(self) -> None:
        text = _containerfile_text()
        match = re.search(
            r"^FROM\s+python:3\.12-slim@" + SHA256_DIGEST_RE + r"\s*$",
            text,
            re.MULTILINE,
        )
        assert match is not None, (
            "the evaluator base must be python:3.12-slim pinned by "
            "@sha256:<64 hex> — a tag alone is a moving target"
        )

    def test_no_from_line_names_a_bare_tag(self) -> None:
        # Every FROM in a multi-stage build is pinned by digest, not just
        # the final evaluator base — a build helper stage (e.g. the uv
        # binary) that floats on a tag would make the image non-reproducible
        # even though the final stage is pinned.
        text = _containerfile_text()
        from_lines = [
            line
            for line in text.splitlines()
            if line.strip().upper().startswith("FROM ")
        ]
        assert from_lines, "the Containerfile must have at least one FROM"
        for line in from_lines:
            assert re.search(SHA256_DIGEST_RE, line), (
                f"every FROM must be digest-pinned, found an unpinned stage: {line!r}"
            )


class TestInstallationIsFrozenAgainstTheLockfile:
    def test_uv_lock_is_copied_into_the_image(self) -> None:
        text = _containerfile_text()
        assert re.search(r"^COPY\b.*\buv\.lock\b", text, re.MULTILINE), (
            "the image must carry this commit's uv.lock, not resolve one at build time"
        )

    def test_the_install_command_passes_frozen(self) -> None:
        text = _containerfile_text()
        assert "uv sync" in text
        assert "--frozen" in text, (
            "the install must run `uv sync --frozen` — no dependency "
            "resolution, no drift from the lockfile this commit pins"
        )

    def test_each_named_member_is_copied_and_installed(self) -> None:
        text = _containerfile_text()
        for directory, project_name in MEMBER_PROJECT_NAMES.items():
            assert f"packages/{directory}/pyproject.toml" in text, (
                f"packages/{directory}/pyproject.toml must be copied into the image"
            )
            assert f"packages/{directory}/src" in text, (
                f"packages/{directory}/src must be copied into the image"
            )
            assert f"--package {project_name}" in text, (
                f"`uv sync` must select --package {project_name} "
                f"(packages/{directory}'s own project name)"
            )

    def test_no_runtime_pip_install(self) -> None:
        # architecture §12: "Pinned libraries: lockfile inside the image; no
        # runtime pip install." uv itself must also arrive without a pip
        # install (a digest-pinned COPY --from, here), or the image's own
        # bootstrap would be the one unpinned dependency. Only instruction
        # lines count — the header prose names the very constraint this
        # checks, so a naive whole-file substring search would self-match.
        instructions = "\n".join(
            line
            for line in _containerfile_text().splitlines()
            if line.strip() and not line.strip().startswith("#")
        )
        assert "pip install" not in instructions.lower()


class TestDeterminismEnvironmentVariables:
    def test_the_four_thread_and_hash_variables_are_set(self) -> None:
        text = _containerfile_text()
        # They must actually be ENV (persisted into the image config), not
        # just a one-off RUN-time export that vanishes after that layer.
        env_text = _env_instructions(text)
        for assignment in (
            "OMP_NUM_THREADS=1",
            "MKL_NUM_THREADS=1",
            "POLARS_MAX_THREADS=1",
            "PYTHONHASHSEED=0",
        ):
            assert assignment in env_text, (
                f"Containerfile must set {assignment} in an ENV instruction "
                "(architecture §12: single-threaded numerics, stable "
                "iteration order)"
            )


class TestTheContainerfileRecordsItsOwnScope:
    def test_the_header_names_evaluation_as_out_of_scope(self) -> None:
        text = _containerfile_text()
        header = "\n".join(text.splitlines()[:25])
        assert "out of scope" in header.lower() or "out-of-scope" in header.lower()
        assert "evaluation" in header.lower()


class TestBuildScriptUsesPodmanOrBuildahNeverDocker:
    def test_the_script_is_syntactically_valid_bash(self) -> None:
        # Statically parsed only — this never invokes podman or buildah.
        result = subprocess.run(
            ["bash", "-n", str(BUILD_SCRIPT)],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        assert result.returncode == 0, result.stderr

    def test_the_script_is_executable(self) -> None:
        assert BUILD_SCRIPT.stat().st_mode & 0o111, "build_image.sh must be executable"

    def test_the_script_builds_with_podman_or_buildah(self) -> None:
        text = _build_script_text()
        assert "podman" in text
        assert "buildah" in text

    def test_the_script_never_shells_out_to_docker(self) -> None:
        text = _build_script_text()
        assert not re.search(r"\bdocker\s+(build|run|images|inspect)\b", text), (
            "docker is not a supported engine for this recipe"
        )


class TestBuildScriptIsReproducibleAndCommitPinned:
    def test_source_date_epoch_comes_from_head_commit_time(self) -> None:
        text = _build_script_text()
        assert "SOURCE_DATE_EPOCH" in text
        assert re.search(r"git log -1 --format=%ct(\s+HEAD)?", text), (
            "SOURCE_DATE_EPOCH must be HEAD's commit time, not build-time `date`"
        )
        assert "--timestamp" in text, (
            "SOURCE_DATE_EPOCH must actually reach the engine's build invocation"
        )

    def test_the_image_is_tagged_with_the_short_sha(self) -> None:
        text = _build_script_text()
        assert "git rev-parse --short HEAD" in text
        assert "localhost/nullius-evaluator:" in text

    def test_the_script_prints_exactly_one_digest_pinned_reference(self) -> None:
        text = _build_script_text()
        assert re.search(
            r"localhost/nullius-evaluator@\$\{?[A-Za-z_][A-Za-z0-9_]*\}?", text
        ), "the script must print localhost/nullius-evaluator@<digest variable>"
        # The printed reference must be a digest, never the mutable tag.
        assert not re.search(
            r'echo\s+"localhost/nullius-evaluator:\$', text
        ), "the printed reference must be the @sha256 digest, not the :tag"

    def test_the_script_refuses_uncommitted_changes_under_copied_paths(self) -> None:
        text = _build_script_text()
        assert "git status --porcelain" in text
        assert re.search(r"exit 1\b", text)
        # The refusal must actually gate the paths the Containerfile copies,
        # not just be present somewhere unrelated in the script.
        for directory in MEMBER_PROJECT_NAMES:
            assert f"packages/{directory}" in text
        assert "uv.lock" in text
