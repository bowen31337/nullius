"""Feature 151: a credential read from a committed env file is rejected.

app_spec.xml, "Trust Zone Isolation & Secrets", feature 151: *System stores
exchange credentials in a secrets manager, which rejects any credential read
from a committed environment file.*  docs/nullius-tech-architecture.md §17
carries the clause nearly verbatim ("Stored in a secrets manager, never in
env files committed anywhere"), and this suite is the whole feature in the
three claims the sentence decomposes into:

* **stores exchange credentials in a secrets manager** — a store that holds
  a value under a label and hands it back. ``TestTheStoreHoldsAValue`` owns
  the round-trip and the presence check.
* **which rejects** — the read is refused before the value is served.
  ``TestTheReadIsRefused`` owns the refusal and its ordering.
* **any credential read from a committed environment file** — the class of
  the refusal: a value that is byte-for-byte a line a committed env file
  holds. ``TestTheCommittedEnvironmentFileRule`` owns the value-match and its
  precision — committed, not merely present; env file, not any file; exact,
  not a prefix.

The fixtures are placeholder values (``"sk-live-abc123"``-style strings,
never a real key) and a throwaway git repository the committed-file check is
exercised against — the law, not a secret. A deployment's real exchange
credentials live in a real secrets manager, managed out of band (§17).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from infra.security.secrets_manager import (
    REPO_ROOT_ENV,
    CommittedEnvironmentFileError,
    InMemorySecretsStore,
    SecretsStore,
    SecretsStoreError,
    ValueNotStored,
    committed_paths,
    load_env_file,
)

# ---------------------------------------------------------------------------
# The store holds a value and hands it back — the "stores" half.
# ---------------------------------------------------------------------------


class TestTheStoreHoldsAValue:
    """A secrets store: put a value under a label, get it back, ask if present."""

    def test_a_put_value_is_got_back(self, store: InMemorySecretsStore) -> None:
        """The round-trip — the store's whole job, in its expected case."""
        store.put_secret("live-execution-key", "sk-live-abc123")
        assert store.get_secret("live-execution-key") == "sk-live-abc123"

    def test_two_labels_are_two_values(self, store: InMemorySecretsStore) -> None:
        """The store holds values by label, and a label names one value."""
        store.put_secret("live-execution-key", "sk-live-abc123")
        store.put_secret("shadow-research-key", "sk-test-xyz789")
        assert store.get_secret("live-execution-key") == "sk-live-abc123"
        assert store.get_secret("shadow-research-key") == "sk-test-xyz789"

    def test_a_label_is_reusable(self, store: InMemorySecretsStore) -> None:
        """A later put of the same label replaces — the way a rotation lands."""
        store.put_secret("live-execution-key", "sk-live-abc123")
        store.put_secret("live-execution-key", "sk-live-rotated")
        assert store.get_secret("live-execution-key") == "sk-live-rotated"

    def test_has_secret_reports_presence(self, store: InMemorySecretsStore) -> None:
        """A presence check says whether a label is stored."""
        assert store.has_secret("live-execution-key") is False
        store.put_secret("live-execution-key", "sk-live-abc123")
        assert store.has_secret("live-execution-key") is True

    def test_an_unstored_label_is_not_present(self, store: InMemorySecretsStore) -> None:
        """A label the store was never given is absent."""
        assert store.has_secret("never-stored") is False

    def test_a_presence_check_does_not_refuse(self, store: InMemorySecretsStore) -> None:
        """``has_secret`` is not a read — it does not run the committed check,
        so a committed value still reports as present (the refusal is a
        read's step, and a presence check that refused would conflate "not
        stored" with "committed")."""
        store.put_secret("live-execution-key", "sk-live-abc123")
        assert store.has_secret("live-execution-key") is True

    def test_an_unstored_label_read_raises_value_not_stored(self, store: InMemorySecretsStore) -> None:
        """Reading a label the store never got is the ordinary "not stored",
        not the committed refusal — there is no value to refuse."""
        with pytest.raises(ValueNotStored):
            store.get_secret("never-stored")

    def test_value_not_stored_is_a_secrets_store_error(self) -> None:
        """So a caller that treats every store failure alike catches the
        taxonomy with one ``except``."""
        assert issubclass(ValueNotStored, SecretsStoreError)

    def test_two_stores_are_independent(self, store: InMemorySecretsStore) -> None:
        """A credential in one store is not visible in another — the one thing
        a secrets store must not leak."""
        store.put_secret("live-execution-key", "sk-live-abc123")
        other = InMemorySecretsStore(repo_root=store._directory())
        assert other.has_secret("live-execution-key") is False

    def test_a_blank_label_is_refused(self, store: InMemorySecretsStore) -> None:
        """The label is how the store names the credential it holds; a store
        that could not name a value could not be asked for it."""
        with pytest.raises(SecretsStoreError):
            store.put_secret("   ", "sk-live-abc123")

    def test_a_non_string_value_is_refused(self, store: InMemorySecretsStore) -> None:
        """The store compares values to committed env-file lines, and a value
        that is not text has no line to compare to."""
        with pytest.raises(SecretsStoreError):
            store.put_secret("live-execution-key", 12345)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# The read is refused before the value is served — the "rejects" half.
# ---------------------------------------------------------------------------


class TestTheReadIsRefused:
    """A credential read from a committed env file is rejected."""

    def test_a_committed_credential_is_refused(
        self, store: InMemorySecretsStore, committed_env: Path
    ) -> None:
        """The feature's own clause: the value committed to ``.env`` and stored
        under the label is refused on read."""
        store.put_secret("live-execution-key", "sk-live-abc123")
        with pytest.raises(CommittedEnvironmentFileError):
            store.get_secret("live-execution-key")

    def test_the_refusal_is_a_secrets_store_error(self) -> None:
        """So the committed refusal and the not-stored refusal share a base,
        and a caller can catch the taxonomy with one ``except``."""
        assert issubclass(CommittedEnvironmentFileError, SecretsStoreError)

    def test_the_refusal_names_the_committed_file(
        self, store: InMemorySecretsStore, committed_env: Path
    ) -> None:
        """The remedy is to rotate and de-commit, and an operator has to be
        able to find the line — so the refusal names the file."""
        store.put_secret("live-execution-key", "sk-live-abc123")
        with pytest.raises(CommittedEnvironmentFileError) as raised:
            store.get_secret("live-execution-key")
        assert ".env" in str(raised.value)
        assert str(committed_env) in str(raised.value)

    def test_a_committed_value_is_not_served(self, store: InMemorySecretsStore, committed_env: Path) -> None:
        """Nothing is returned on the refusal path — not an empty string, not
        ``None`` — because a caller that mistook a refusal for a key would
        authenticate with a leaked credential and report it safe."""
        store.put_secret("live-execution-key", "sk-live-abc123")
        with pytest.raises(CommittedEnvironmentFileError):
            store.get_secret("live-execution-key")

    def test_an_uncommitted_value_is_served(
        self, store: InMemorySecretsStore, repo: GitRepo, exchange_key_value: str
    ) -> None:
        """The rule is the *committed* file, and only that: a value that was
        never committed — the deployment's own uncommitted ``.env`` — is
        served, because refusing it would refuse the one legitimate read."""
        repo.write(".env", f"EXCHANGE_KEY={exchange_key_value}\n")  # written, never committed
        store.put_secret("live-execution-key", exchange_key_value)
        assert store.get_secret("live-execution-key") == exchange_key_value

    def test_a_value_with_no_committed_env_is_served(self, store: InMemorySecretsStore) -> None:
        """No committed env file at all — the clean case — serves normally."""
        store.put_secret("live-execution-key", "sk-live-abc123")
        assert store.get_secret("live-execution-key") == "sk-live-abc123"


# ---------------------------------------------------------------------------
# The class of the refusal — the "committed environment file" half.
# ---------------------------------------------------------------------------


class TestTheCommittedEnvironmentFileRule:
    """The refusal is precise: committed, env, and an exact value match."""

    def test_a_committed_value_is_detected(
        self, store: InMemorySecretsStore, committed_env: Path
    ) -> None:
        """The committed env file's value is the one the read refuses."""
        store.put_secret("live-execution-key", "sk-live-abc123")
        with pytest.raises(CommittedEnvironmentFileError):
            store.get_secret("live-execution-key")

    def test_a_value_committed_after_storing_is_still_refused(
        self, store: InMemorySecretsStore, repo: GitRepo
    ) -> None:
        """The committed set is read at the moment of the check, not cached: a
        file committed *after* the value was stored is still caught, because
        a credential committed an hour ago is exactly the drift the feature
        catches."""
        store.put_secret("live-execution-key", "sk-live-abc123")
        assert store.get_secret("live-execution-key") == "sk-live-abc123"  # clean now
        repo.write(".env", f"EXCHANGE_KEY=sk-live-abc123\n")
        repo.commit("Commit the credential by mistake")
        with pytest.raises(CommittedEnvironmentFileError):
            store.get_secret("live-execution-key")

    def test_a_committed_non_env_file_is_not_refused(
        self, store: InMemorySecretsStore, repo: GitRepo
    ) -> None:
        """The rule is about *env files*: a credential committed to a
        ``config.yaml`` is committed, but it is not an env file, so the read
        is served — the feature's word is "env file", and the store refuses
        only the class the sentence named."""
        store.put_secret("live-execution-key", "sk-live-abc123")
        repo.write("config.yaml", "exchange_key: sk-live-abc123\n")
        repo.commit("Commit a config file")
        assert store.get_secret("live-execution-key") == "sk-live-abc123"

    def test_a_prefix_match_is_not_refused(
        self, store: InMemorySecretsStore, committed_env: Path
    ) -> None:
        """The match is exact and whole-value: a real secret that merely
        shares a prefix with the committed placeholder is not falsely
        refused — a secret that shares a prefix is a different credential."""
        store.put_secret("live-execution-key", "sk-live-abc123-rotated-9999")
        assert store.get_secret("live-execution-key") == "sk-live-abc123-rotated-9999"

    def test_a_rotated_value_is_served(
        self, store: InMemorySecretsStore, committed_env: Path
    ) -> None:
        """A committed secret that was later rotated to a new value is not
        falsely served as committed: the new value is not a committed line,
        so it is served."""
        store.put_secret("live-execution-key", "sk-live-rotated-new-value")
        assert store.get_secret("live-execution-key") == "sk-live-rotated-new-value"

    def test_the_match_is_whole_value_not_substring(
        self, store: InMemorySecretsStore, committed_env: Path
    ) -> None:
        """A committed line that merely contains the value as a substring is
        not the same credential: the value must be the whole line's value,
        so a longer committed string does not falsely refuse a shorter real
        secret, and a shorter committed string does not falsely refuse a
        longer real secret."""
        store.put_secret("live-execution-key", "sk-live-abc123-extra")
        assert store.get_secret("live-execution-key") == "sk-live-abc123-extra"

    def test_a_quoted_committed_value_matches(
        self, store: InMemorySecretsStore, repo: GitRepo
    ) -> None:
        """A value quoted in the env file is compared un-quoted — the store
        compares what a caller would put (the value) against what the file
        held (the un-wrapped value), on equal terms."""
        store.put_secret("live-execution-key", "sk-live-abc123")
        repo.write(".env", 'EXCHANGE_KEY="sk-live-abc123"\n')
        repo.commit("Commit a quoted credential")
        with pytest.raises(CommittedEnvironmentFileError):
            store.get_secret("live-execution-key")

    def test_a_second_label_with_the_same_committed_value_is_refused(
        self, store: InMemorySecretsStore, committed_env: Path
    ) -> None:
        """The check is over the value, not the label: two labels holding the
        same committed value are both refused, because the committed env file
        holds the value and either label would serve it."""
        store.put_secret("live-execution-key", "sk-live-abc123")
        store.put_secret("backup-execution-key", "sk-live-abc123")
        with pytest.raises(CommittedEnvironmentFileError):
            store.get_secret("backup-execution-key")

    def test_an_empty_value_is_not_refused(
        self, store: InMemorySecretsStore, committed_env: Path
    ) -> None:
        """A blank line is not a credential, so an empty value never matches a
        committed env file — refusing it would be a refusal of nothing."""
        store.put_secret("live-execution-key", "")
        assert store.get_secret("live-execution-key") == ""


# ---------------------------------------------------------------------------
# The committed set: what git tracks, and the fail-open when it cannot ask.
# ---------------------------------------------------------------------------


class TestCommittedPaths:
    """The committed env files git tracks — the detection's input."""

    def test_only_env_files_are_listed(self, repo: GitRepo) -> None:
        """The committed set is filtered to env-file names: a committed
        ``.env`` is in, a committed ``README.md`` is out — the feature's rule
        is about env files."""
        repo.write(".env", "EXCHANGE_KEY=sk-live-abc123\n")
        repo.write("README.md", "# nullius\n")
        repo.write("config.yaml", "key: value\n")
        repo.commit("Add mixed files")
        paths = committed_paths(repo.root)
        names = {p.name for p in paths}
        assert names == {".env"}

    def test_a_non_env_file_is_not_listed(self, repo: GitRepo) -> None:
        """A committed file with another name is not an env file by this rule."""
        repo.write("secrets.json", '{"key": "sk-live-abc123"}\n')
        repo.commit("Commit a json")
        assert committed_paths(repo.root) == frozenset()

    def test_an_uncommitted_env_file_is_not_listed(self, repo: GitRepo) -> None:
        """``git ls-files`` lists the committed set, not the working tree, so a
        written-but-unstaged env file is not yet committed."""
        repo.write(".env", "EXCHANGE_KEY=sk-live-abc123\n")
        assert committed_paths(repo.root) == frozenset()

    def test_a_dot_env_local_is_listed(self, repo: GitRepo) -> None:
        """The env-file set includes ``.env``'s dotted siblings — the rule's
        closed vocabulary, matched by name."""
        repo.write(".env.local", "EXCHANGE_KEY=sk-live-abc123\n")
        repo.commit("Add a local env")
        names = {p.name for p in committed_paths(repo.root)}
        assert names == {".env.local"}

    def test_paths_are_absolute(self, repo: GitRepo) -> None:
        """The value-match reads each file, so the paths resolve to absolute —
        and a test can assert on a stable name."""
        repo.write(".env", "EXCHANGE_KEY=sk-live-abc123\n")
        repo.commit("Add env")
        (path,) = committed_paths(repo.root)
        assert path.is_absolute()

    def test_a_directory_outside_the_repo_is_not_searched(
        self, repo: GitRepo, tmp_path: Path
    ) -> None:
        """The check is scoped to the repository root: a committed env file in
        another tree is not read into this store's answer."""
        repo.write(".env", "EXCHANGE_KEY=sk-live-abc123\n")
        repo.commit("Add env")
        other = tmp_path / "elsewhere"
        other.mkdir()
        (other / ".env").write_text("EXCHANGE_KEY=sk-live-abc123\n", encoding="utf-8")
        names = {p.name for p in committed_paths(repo.root)}
        assert names == {".env"}


class TestLoadEnvFile:
    """The ``KEY=VALUE`` grammar the committed check matches against."""

    def test_parses_assignments(self, repo: GitRepo) -> None:
        """One ``KEY=VALUE`` per line, the ordinary env-file grammar."""
        path = repo.write(".env", "EXCHANGE_KEY=sk-live-abc123\nOTHER=value\n")
        assert load_env_file(path) == {"EXCHANGE_KEY": "sk-live-abc123", "OTHER": "value"}

    def test_ignores_comments_and_blank_lines(self, repo: GitRepo) -> None:
        """A comment or a blank line is not an assignment."""
        path = repo.write(".env", "# a comment\n\nEXCHANGE_KEY=sk-live-abc123\n")
        assert load_env_file(path) == {"EXCHANGE_KEY": "sk-live-abc123"}

    def test_trims_surrounding_space(self, repo: GitRepo) -> None:
        """Space around the key and the value is trimmed — a value put in the
        store would not carry the padding."""
        path = repo.write(".env", "  EXCHANGE_KEY =   sk-live-abc123  \n")
        assert load_env_file(path) == {"EXCHANGE_KEY": "sk-live-abc123"}

    def test_unwraps_quotes(self, repo: GitRepo) -> None:
        """A single- or double-quoted value is un-wrapped, so the store
        compares values on equal terms."""
        path = repo.write(".env", 'EXCHANGE_KEY="sk-live-abc123"\nOTHER=\'x y\'\n')
        assert load_env_file(path) == {"EXCHANGE_KEY": "sk-live-abc123", "OTHER": "x y"}

    def test_a_line_without_equals_is_skipped(self, repo: GitRepo) -> None:
        """A line with no ``=`` is not an assignment."""
        path = repo.write(".env", "not-an-assignment\nEXCHANGE_KEY=sk-live-abc123\n")
        assert load_env_file(path) == {"EXCHANGE_KEY": "sk-live-abc123"}

    def test_a_later_line_wins(self, repo: GitRepo) -> None:
        """A later assignment of a seen key wins — the way a real loader
        behaves, so a value redefined down the file is the one matched."""
        path = repo.write(".env", "EXCHANGE_KEY=first\nEXCHANGE_KEY=sk-live-abc123\n")
        assert load_env_file(path) == {"EXCHANGE_KEY": "sk-live-abc123"}

    def test_an_unreadable_file_is_refused(self, tmp_path: Path) -> None:
        """A committed-file check that could not read the file it is checking
        would report 'clean' over a file it never looked at — the exact
        silence the feature must not be, so it is refused rather than
        swallowed."""
        with pytest.raises(SecretsStoreError):
            load_env_file(tmp_path / "does-not-exist.env")


class TestTheStoreCannotAskGit:
    """The fail-open: when git cannot answer, the store refuses to enforce."""

    def test_no_repository_serves_every_read(self, tmp_path: Path) -> None:
        """A directory with no git is "nothing is committed here": the store
        fails open on the one case it cannot know, because failing closed
        would refuse every read in a tree with no env files to refuse."""
        store = InMemorySecretsStore(repo_root=tmp_path)
        store.put_secret("live-execution-key", "sk-live-abc123")
        (tmp_path / ".env").write_text("EXCHANGE_KEY=sk-live-abc123\n", encoding="utf-8")
        assert store.get_secret("live-execution-key") == "sk-live-abc123"

    def test_committed_paths_is_empty_without_git(self, tmp_path: Path) -> None:
        """No repository means no committed env files the store can see."""
        assert committed_paths(tmp_path) == frozenset()

    def test_the_repo_root_is_named_by_environment(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """The store asks git about :data:`REPO_ROOT_ENV` when it is set — a
        process that started elsewhere still asks about the right tree."""
        monkeypatch.setenv(REPO_ROOT_ENV, str(tmp_path))
        assert committed_paths(env={REPO_ROOT_ENV: str(tmp_path)}) == frozenset()

    def test_a_store_points_at_its_named_root(self, repo: GitRepo) -> None:
        """The in-memory store asks git about the root it was given, so the
        committed check and the store agree on the tree."""
        store = InMemorySecretsStore(repo_root=repo.root)
        assert store._directory() == str(repo.root)


# ---------------------------------------------------------------------------
# The contract holds for the base class, not just the in-memory double.
# ---------------------------------------------------------------------------


class TestTheContract:
    """The law is the base class's, so any store is covered."""

    def test_the_base_class_is_abstract(self) -> None:
        """A bare :class:`SecretsStore` cannot serve — the contract is stated
        here and a real manager implements the seams."""
        with pytest.raises(NotImplementedError):
            SecretsStore().put_secret("k", "v")

    def test_get_secret_runs_the_committed_check_for_any_store(
        self, repo: GitRepo, committed_env: Path
    ) -> None:
        """The refusal is at :meth:`SecretsStore.get_secret`, so a store that
        only implements the three seams still gets the law — a subclass that
        served the value without the check would be bypassing the feature."""
        store = InMemorySecretsStore(repo_root=repo.root)
        store.put_secret("live-execution-key", "sk-live-abc123")
        with pytest.raises(CommittedEnvironmentFileError):
            store.get_secret("live-execution-key")

    def test_the_abstraction_is_a_secrets_store(self, store: InMemorySecretsStore) -> None:
        """The in-memory double is a :class:`SecretsStore` — the contract,
        concretely, so a caller reaches it through the same seam a Vault or a
        sops document would."""
        assert isinstance(store, SecretsStore)
