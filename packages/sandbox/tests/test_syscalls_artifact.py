"""Feature 160's committed ceiling: the file on disk, held to §5.2's posture.

The sixth artifact-backed feature in this category ships a JSON file beside its
law, and this suite is the one that reads it — the *other* suites build
documents in memory, deliberately, so that a drift in the file cannot hide
behind a builder that never opened it.  What is stated here is what an operator
auditing this deployment can conclude from a checkout:

* the file is where the law says it is, and compiles through the same law any
  change to it would be compiled through — no privileged path, no shortcut;
* its default action **denies** (§5.2's row is an *allowlist*; a default of
  ``allow``, or of the ``log``/``trace``/``notify`` spellings that observe a
  syscall and let it through, is a container that believes it is sandboxed);
* every term it admits is a well-formed syscall name listed once, and there is a
  way for the process to end;
* **which** syscalls it admits is the reviewed list — because §5.2's table names
  the mechanism and no names, the ceiling's *content* is a deployment's decision
  rather than a spec number, and the sweep at the bottom of this file is what
  makes that decision reviewable;
* the families §3's zone map denies — the filesystem, the network, process
  creation, kernel entropy, the escape surface and the namespace/filter surface
  — are absent, so the positive list is a sandbox rather than a description.

The compiler is not wider than the file: the last class pins the set of keys a
document may carry, so a key nothing reads cannot hide in the artifact and
widen it silently.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import sandbox
from _documents import (
    ADMITTED_SYSCALL,
    ALLOW_ACTION,
    COMMITTED_SYSCALL_TERMS,
    DISALLOWED_SYSCALL,
    ERRNO_ACTION,
    FORBIDDEN_SYSCALL_TERMS,
    KILL_ACTION,
    syscalls_document,
)
from sandbox.syscalls import (
    ALLOWING_ACTIONS,
    COMMITTED_SYSCALLS_POLICY,
    DENYING_ACTIONS,
    SYSCALLS_POLICY_KIND,
    TERMINATION_SYSCALLS,
    committed_syscalls_policy,
    compile_syscalls_policy,
    load_syscalls_policy,
)
from sandbox.syscalls import (
    KILL_ACTION as LAW_KILL,
)

#: The artifact as it ships, read as text rather than through the law — so a
#: test that means "what is in the file" is not answered by the thing under test.
ARTIFACT = Path(sandbox.__file__).resolve().parent / "syscalls_allowlist.json"


def _raw() -> dict:
    with ARTIFACT.open("r", encoding="utf-8") as handle:
        return json.load(handle)


class TestTheArtifact:
    """Where the file is, what it is called, and that it is JSON."""

    def test_the_law_points_at_the_file_on_disk(self) -> None:
        assert COMMITTED_SYSCALLS_POLICY == ARTIFACT
        assert COMMITTED_SYSCALLS_POLICY.name == "syscalls_allowlist.json"
        assert COMMITTED_SYSCALLS_POLICY.is_file()

    def test_the_file_ships_beside_the_law_that_checks_it(self) -> None:
        # A checkout cannot hold one without the other, which is the whole
        # reason the artifact lives in the package rather than in a deployment
        # directory: the ceiling and the law that holds it are one provenance.
        assert ARTIFACT.parent == Path(sandbox.syscalls.__file__).resolve().parent

    def test_the_file_is_a_json_object(self) -> None:
        assert isinstance(_raw(), dict)

    def test_it_declares_itself_the_kind_the_law_reads(self) -> None:
        assert _raw()["policy"] == SYSCALLS_POLICY_KIND == "sandbox-syscalls"

    def test_it_carries_an_explanatory_comment(self) -> None:
        # A committed ceiling is a reviewed document: an operator reading the
        # artifact should find, in the file, why the default must deny and why
        # each family is absent — rather than having to reconstruct the argument
        # from the diff that added it.  A list of lines rather than one string,
        # which is the shape every other artifact in this member takes
        # (``isolation_policy.json``, ``imports_allowlist.json``,
        # ``timeout_policy.json``, ``budget_policy.json``): a JSON string with
        # embedded newlines reads as one wrapped paragraph in a diff and as a
        # single unreadable line in a terminal.
        comment = _raw()["_comment"]
        assert isinstance(comment, list)
        assert all(isinstance(line, str) for line in comment)
        assert len(comment) >= 20
        joined = "\n".join(comment)
        assert "seccomp" in joined
        assert "5.2" in joined
        assert "default" in joined

    def test_the_comment_argues_every_absent_family(self) -> None:
        # The prose half of the ceiling's review: the file itself says why the
        # filesystem, the network, process creation and kernel entropy are
        # absent, so a reader does not have to infer the posture from a list of
        # what *is* there.
        joined = "\n".join(_raw()["_comment"]).lower()
        for family in ("filesystem", "network", "fork", "entropy"):
            assert family in joined, family

    def test_the_law_reads_the_committed_file_not_a_copy(self) -> None:
        # The same object content, reached two ways: the convenience function
        # and the explicit loader must agree, because a deployment's audit and
        # its runtime must be reading one ceiling.
        assert (
            committed_syscalls_policy().allowed()
            == load_syscalls_policy(ARTIFACT).allowed()
        )


class TestTheCommittedCeiling:
    """What the artifact says once the law has compiled it."""

    def test_the_default_action_denies(self) -> None:
        # The one field a reviewer checks first, and the whole reason the
        # compiler refuses the other spellings.
        policy = committed_syscalls_policy()
        assert policy.default_action in DENYING_ACTIONS
        assert policy.default_action == LAW_KILL == KILL_ACTION

    def test_the_committed_action_is_the_one_section_15_names(self) -> None:
        # §15: "Sandbox escape attempt | seccomp violation | Kill, record
        # fail_class, quarantine the node and its subtree."  The artifact
        # commits to the kill, so a violation is a process the kernel destroyed
        # — which is what makes feature 161's quarantine the right recovery.
        assert committed_syscalls_policy().default_action == "kill"

    def test_every_admitted_term_is_a_well_formed_syscall_name(self) -> None:
        for term in committed_syscalls_policy().allowed():
            assert term == term.strip()
            assert term == term.lower()
            assert term.isidentifier(), term

    def test_no_term_is_listed_twice(self) -> None:
        terms = committed_syscalls_policy().allowed()
        assert len(terms) == len(set(terms))

    def test_the_ceiling_admits_a_way_for_the_process_to_end(self) -> None:
        # The compiler's third requirement, stated against the real file: the
        # box can terminate itself, so a candidate's death is the candidate's
        # rather than a filter that admits nothing.
        policy = committed_syscalls_policy()
        assert TERMINATION_SYSCALLS.intersection(policy.allowed())

    def test_the_ceiling_is_not_empty_and_is_not_everything(self) -> None:
        # Both directions matter and they are different failures: an empty
        # ceiling kills every candidate at its first instruction, and a ceiling
        # that admitted everything would be a filter with nothing to refuse.
        policy = committed_syscalls_policy()
        assert 0 < len(policy.allowed()) < 200

    def test_the_compiled_ceiling_is_a_policy_not_a_document(self) -> None:
        policy = committed_syscalls_policy()
        assert type(policy).__name__ == "SyscallPolicy"
        assert policy.kind == SYSCALLS_POLICY_KIND


class TestTheCommittedPosture:
    """Which syscalls this deployment admits — the reviewed content."""

    def test_the_admitted_terms_are_the_reviewed_list(self) -> None:
        # Compared as two literal lists rather than against the file itself: a
        # term moving in or out of the ceiling is a posture change a reviewer
        # should have to make deliberately, and this assertion is where they
        # make it.
        assert sorted(committed_syscalls_policy().allowed()) == sorted(
            COMMITTED_SYSCALL_TERMS
        )

    def test_the_committed_terms_are_the_files_terms(self) -> None:
        # The other half of the same fact, read straight off disk: the builder's
        # tuple and the artifact cannot drift apart, and this is the pair that
        # says so rather than the law's own re-export.
        assert sorted(_raw()["allow"]) == sorted(COMMITTED_SYSCALL_TERMS)

    def test_an_ordinary_call_is_admitted(self) -> None:
        assert committed_syscalls_policy().admits(ADMITTED_SYSCALL) is True

    @pytest.mark.parametrize("term", FORBIDDEN_SYSCALL_TERMS)
    def test_no_denied_family_is_admitted(self, term: str) -> None:
        # Swept one term at a time so a failure names the syscall that got in
        # rather than reporting that two lists differ.
        assert committed_syscalls_policy().admits(term) is False, term

    def test_the_filesystem_family_is_absent(self) -> None:
        # §5.2: "Filesystem | No mounts. Data arrives over IPC only."  A box
        # that opened a file would be one whose structural denial failed, and
        # the ceiling is the second line of that defence.
        policy = committed_syscalls_policy()
        assert policy.admits(DISALLOWED_SYSCALL) is False
        assert not [t for t in policy.allowed() if t.startswith("open")]
        assert not [t for t in policy.allowed() if t.startswith("stat")]

    def test_the_network_family_is_absent(self) -> None:
        # §5.2: "Network | Namespace with no interfaces. Not a firewall rule."
        # The namespace is what enforces that; the ceiling does not need to
        # carry a socket rule, but it must not *admit* one either.
        policy = committed_syscalls_policy()
        assert not [t for t in policy.allowed() if t.startswith("socket")]
        assert not [t for t in policy.allowed() if t in ("connect", "bind", "listen")]

    def test_kernel_entropy_is_absent(self) -> None:
        # Feature 165's subject: a run's randomness is the seed the dispatcher
        # drew and persisted, not a draw from the host — and a run that read the
        # host's entropy would be one whose replay the seed could not reproduce.
        assert committed_syscalls_policy().admits("getrandom") is False

    def test_the_escape_surface_is_absent(self) -> None:
        # §15's row, at the ceiling: the syscalls a confined process would use
        # to read or write another process's memory, and to lift its own filter.
        policy = committed_syscalls_policy()
        for term in ("ptrace", "process_vm_readv", "process_vm_writev", "seccomp"):
            assert policy.admits(term) is False, term

    def test_process_creation_is_absent(self) -> None:
        # A fork escapes the containment and is not accounted by the cgroup's
        # ``pids.max``, so the ceiling is where it is refused.
        policy = committed_syscalls_policy()
        for term in ("fork", "vfork", "clone", "clone3", "execve"):
            assert policy.admits(term) is False, term

    def test_the_ceiling_is_a_named_list_rather_than_a_pattern(self) -> None:
        # Coverage is by exact name, deliberately unlike feature 167's dotted
        # prefix ceiling: a syscall name is an atom, and ``openat2`` is not
        # "under" ``openat``.  Stated as behaviour rather than as a comment.
        policy = committed_syscalls_policy()
        assert policy.admits("read") is True
        assert policy.admits("readv") is True
        assert policy.admits("readdir") is False


class TestTheArtifactIsRefusedWhole:
    """A drifted artifact does not compile — the widening drift above all."""

    def _compile_file(self, tmp_path: Path, document: dict):
        path = tmp_path / "syscalls_allowlist.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        return load_syscalls_policy(path)

    def test_a_default_of_allow_is_refused(self, tmp_path: Path) -> None:
        # The drift this law exists for.  A filter whose default is ``allow``
        # admits every syscall it does not name, so this artifact would be an
        # ordinary container that believes it is sandboxed.
        document = _raw() | {"default_action": ALLOW_ACTION}
        with pytest.raises(Exception) as raised:
            self._compile_file(tmp_path, document)
        assert type(raised.value).__name__ == "SyscallsDocumentError"
        assert ALLOW_ACTION in str(raised.value)

    @pytest.mark.parametrize("action", ALLOWING_ACTIONS)
    def test_the_observing_actions_are_refused(
        self, tmp_path: Path, action: str
    ) -> None:
        # ``log``, ``trace`` and ``notify`` are the near-misses: each *observes*
        # the syscall and, by seccomp's own defaults, lets it through.  A
        # deployment running under ``notify`` and believing it was sandboxed is
        # the exact failure this refusal prevents.
        document = _raw() | {"default_action": action}
        with pytest.raises(Exception) as raised:
            self._compile_file(tmp_path, document)
        assert type(raised.value).__name__ == "SyscallsDocumentError"

    def test_the_errno_reading_is_legal_but_is_not_what_ships(
        self, tmp_path: Path
    ) -> None:
        # The other denying spelling compiles — it is a genuine ceiling — and
        # the committed artifact still takes the kill, because §15's consequence
        # is the one this deployment means.  Stated so a reader can tell the two
        # facts apart: "``errno`` is legal" is not "``errno`` is committed".
        policy = self._compile_file(tmp_path, _raw() | {"default_action": ERRNO_ACTION})
        assert policy.default_action == ERRNO_ACTION
        assert committed_syscalls_policy().default_action == KILL_ACTION

    def test_a_missing_file_is_refused_rather_than_defaulted(
        self, tmp_path: Path
    ) -> None:
        # An unreadable policy is not a filter that refuses everything
        # gracefully — it is a deployment with no syscall law at all.
        with pytest.raises(Exception) as raised:
            load_syscalls_policy(tmp_path / "absent.json")
        assert type(raised.value).__name__ == "SyscallsDocumentError"

    def test_a_file_that_is_not_json_is_refused(self, tmp_path: Path) -> None:
        path = tmp_path / "syscalls_allowlist.json"
        path.write_text("{ not json", encoding="utf-8")
        with pytest.raises(Exception) as raised:
            load_syscalls_policy(path)
        assert type(raised.value).__name__ == "SyscallsDocumentError"

    def test_a_file_that_is_not_a_mapping_is_refused(self, tmp_path: Path) -> None:
        path = tmp_path / "syscalls_allowlist.json"
        path.write_text(json.dumps(["read", "write"]), encoding="utf-8")
        with pytest.raises(Exception) as raised:
            load_syscalls_policy(path)
        assert type(raised.value).__name__ == "SyscallsDocumentError"

    def test_dropping_the_default_action_is_refused(self, tmp_path: Path) -> None:
        document = _raw()
        del document["default_action"]
        with pytest.raises(Exception) as raised:
            self._compile_file(tmp_path, document)
        assert type(raised.value).__name__ == "SyscallsDocumentError"

    def test_dropping_every_termination_is_refused(self, tmp_path: Path) -> None:
        # The artifact minus its ``exit``/``exit_group``: a filter that admits
        # nothing that ends the process kills every candidate at its first
        # instruction and leaves nobody to record that it did.
        document = _raw() | {
            "allow": [
                term for term in _raw()["allow"] if term not in TERMINATION_SYSCALLS
            ]
        }
        with pytest.raises(Exception) as raised:
            self._compile_file(tmp_path, document)
        assert type(raised.value).__name__ == "SyscallsDocumentError"


class TestTheCompilerIsNotWiderThanTheFile:
    """No key the law does not read can hide in the artifact."""

    def test_the_documents_keys_are_exactly_the_ones_the_law_reads(self) -> None:
        # Pinned so a key nothing reads cannot sit in the file and widen the
        # ceiling silently: the compiler reads ``policy``, ``default_action``
        # and ``allow``, and ``_comment`` is the reviewed explanation.  A new
        # key is a change to this law, and it has to be made here too.
        assert set(_raw()) == {"policy", "default_action", "allow", "_comment"}

    def test_a_stray_key_does_not_widen_the_compiled_ceiling(self) -> None:
        # The behavioural half of the same fact: whatever else a document
        # carries, the compiled policy is the default action and the allow list.
        document = syscalls_document() | {"deny": ["everything"], "extra": 1}
        policy = compile_syscalls_policy(document)
        assert policy.allowed() == tuple(document["allow"])

    def test_the_comment_is_not_read_as_a_ceiling(self) -> None:
        # ``_comment`` is prose.  A document whose comment happened to name a
        # syscall must not thereby admit it — which is a real hazard given that
        # the committed comment names every *denied* family by name.
        document = syscalls_document() | {"_comment": DISALLOWED_SYSCALL}
        assert compile_syscalls_policy(document).admits(DISALLOWED_SYSCALL) is False

    def test_the_artifact_is_compiled_through_the_public_compiler(self) -> None:
        # No privileged path: the file an operator edits is compiled by the
        # same function a CI check calls, so "it compiles in CI" and "it
        # compiles at build time" cannot disagree.
        assert compile_syscalls_policy(_raw()).allowed() == (
            committed_syscalls_policy().allowed()
        )
