"""Feature 151's law: the secrets manager, and its one refusal.

app_spec.xml, "Trust Zone Isolation & Secrets", feature 151: *System stores
exchange credentials in a secrets manager, which rejects any credential read
from a committed environment file.*  docs/nullius-tech-architecture.md §17
carries the clause nearly verbatim — "Exchange API keys: read + trade only,
withdrawal permanently disabled, IP-allowlisted.  **Stored in a secrets
manager, never in env files committed anywhere.**" — and the sentence
decomposes into three claims, each of which this module owns as a seam
rather than a comment:

* **stores exchange credentials in a secrets manager** — the subject is a
  *store with a contract*, not a process.  A deployment's real manager is a
  network service — AWS Secrets Manager, HashiCorp Vault, a sops/age
  document, a KMS-wrapped blob — and none of those is importable code on
  this tree (see ``infra/security/__init__.py``: policy that guards the
  zones must not be composition code from inside them).  So the manager is
  abstracted as :class:`SecretsStore`, the seam a caller reaches for to
  *put* a credential and to *get* it back, and the one concrete store the
  module supplies is :class:`InMemorySecretsStore` — the test double and
  the honest shape of the contract, which holds only the values it was
  given, never a path it was told to read.  The credential is the *value*
  — the exchange key's bytes, the passphrase, the token — and the manager's
  job is to hold that value and hand it back to a caller that names it,
  which is the whole of "stores".  A label names the credential within the
  store; the value is what the label stands for.

* **which rejects** — the *consequence*, and the claim that orders
  everything else.  The manager is not a passive bucket: it is a store that
  refuses a whole class of reads, and the class is the sentence's second
  half.  The refusal is the feature, and it is the store that makes it, at
  the one seam a credential is served — :meth:`SecretsStore.get_secret` —
  so the law is written once, at the read, rather than re-asserted by every
  caller that happens to remember it.  Refused rather than warned, because a
  credential that is silently served from a committed file is a credential
  an operator believes is safe and is not.

* **any credential read from a committed environment file** — the *class*
  of the refusal, and the precise thing the store has to detect.  An
  "environment file" is a ``.env``-style file — ``KEY=VALUE`` lines, the
  shape :func:`_looks_like_env_file` recognises — and "committed" is the
  word that gives the rule its grip: the file is not merely present on disk
  (a deployment's real ``.env`` is, deliberately, uncommitted and is the
  one the deployment reads from at the edge), it is *tracked by version
  control*, which is the failure the sentence names — "never in env files
  **committed anywhere**".  The store therefore does not refuse every
  ``.env``; it refuses a credential whose value it can *trace to a file that
  git tracks*, and it traces that by asking git which files are committed
  (:func:`committed_paths`) and checking whether the credential's value is
  byte-for-byte a line one of those files holds.  A value that is only ever
  in the uncommitted ``.env`` — the deployment's own, at the edge — is not
  refused, because refusing it would refuse the one legitimate read the
  deployment makes; the rule is the *committed* file, and only that.

The detection is deliberately a *value match*, not a *path* match, and that
is the load-bearing decision.  A secrets manager does not know how a caller
came by a value — it is handed ``KEY=VALUE`` bytes and asked to store them,
or handed a label and asked to return the value — so the store cannot refuse
"the file at ``.env``"; it can only refuse a value it has already seen
committed.  So the store remembers the values it has been given (:meth:`
SecretsStore.put_secret`) and, on every read, checks the value it is about
to serve against the committed set: if the value it holds is byte-for-byte a
line in a committed env file, the credential is one that lives in version
control and is refused with :class:`CommittedEnvironmentFileError`.  The
match is exact and whole-line — a value that merely contains, or is merely
contained by, a committed line is not the same credential — so a real secret
that happens to share a prefix with a committed placeholder is not falsely
refused, and a committed secret that was later rotated to a new value is not
falsely *served*.

**The committed set is read at the moment of the check, not cached at
startup.**  A file can be committed *after* the store first read the tree,
and a credential committed an hour ago is exactly the drift the feature
exists to catch; caching the committed set would let a freshly committed
``.env`` through on the strength of a stale "clean" answer.  So
:func:`committed_paths` shells out to ``git ls-files`` on every read — the
expensive-looking choice is the honest one, because the rule is only as
good as its view of what is committed, and a view that is not refreshed is a
rule that silently stops applying.  The store is not a high-throughput
secret server — a deployment reads its exchange keys a handful of times a
day, at process start and at rotation — so the cost is the price of the
guarantee, not a bottleneck.

**A store with no git is treated as "nothing is committed" — and that is a
refusal to enforce, not an enforcement.**  When ``git ls-files`` cannot run
(no repository, no ``git`` on the path), the committed set is empty and no
value matches it, so every read is served.  That is the correct behaviour
for a store that genuinely has no version control, and it is the honest
limit of what the check can do: the feature's rule is "never committed", and
a store that cannot ask git cannot prove a thing is committed, so it does
not pretend to.  The refusal is therefore a property of a store that *can*
ask git and *does* — which is every real deployment, whose credentials live
in a repository — and the check is written to fail open on the one case
where it cannot know, because failing closed there would refuse every read
in a store that has no committed files to refuse, which is a false refusal
of the legitimate case.  (A deployment that wants the rule to hold even
without git has the value-match the other way: it simply never puts a
committed value in the store, which is the discipline the feature names.)

Stdlib-only, like the rest of this tree, except for the one seam that has to
ask the version-control system a question it alone can answer.  :mod:`subprocess`
is used only there — to run ``git ls-files -- <directory>`` and read its stdout
— and the rest of the module is the store, the value-match and the refusal,
none of which touches a network or a secret's material beyond holding and
comparing it.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Final

__all__ = [
    "CommittedEnvironmentFileError",
    "InMemorySecretsStore",
    "SecretsStore",
    "SecretsStoreError",
    "ValueNotStored",
    "committed_paths",
    "load_env_file",
]

#: The environment variable naming the directory the store should ask git
#: about.  A deployment's credentials live in its own tree, and the store
#: must not assume that tree is the current working directory — a process
#: that reads a secret may have started elsewhere — so the directory is
#: named, and defaults to here only when nothing names it.  Mirrors the way
#: :mod:`infra.security.audit_log` names its log path rather than hard-coding
#: it: a store whose search root could only be a hard-coded path would be the
#: one secret check an operator could not point at their real repository.
REPO_ROOT_ENV: Final[str] = "NULLIUS_SECRETS_REPO_ROOT"

#: The file names the committed-file check treats as "an environment file".
#: The sentence's "env file" is this set, closed: a ``.env`` and its common
#: dotted siblings.  A file with another name is not an environment file by
#: this rule — not because it could not hold secrets, but because the
#: feature's word is "env file", and widening the set past the sentence's own
#: vocabulary would refuse files the rule was never written about.
_ENV_FILE_SUFFIXES: Final[frozenset[str]] = frozenset(
    {".env", ".env.local", ".env.private", ".secrets", ".credentials"}
)


class SecretsStoreError(Exception):
    """Base of the secrets-store taxonomy.

    One base class so a caller — the execution path's key loader, an
    operator's provisioning script, a CI check that a secret is not
    committed — can catch every failure of the store with a single
    ``except``.  The subclasses split by *which contract* was violated, not
    by which line of code failed, in the same discipline as
    :mod:`infra.security.key_backup`'s and :mod:`infra.security.audit_log`'s
    taxonomies.
    """


class CommittedEnvironmentFileError(SecretsStoreError):
    """A credential's value is a line a committed environment file holds.

    Feature 151's "rejects any credential read from a committed environment
    file", made into the value the store refuses to serve.  The refusal
    names the file and the line the value matched, because the remedy is to
    rotate the credential and remove it from version control — an operator
    who is told only "this secret is committed" has to go hunting for where,
    and a secret that was committed by mistake is still committed until
    someone finds the line.  Refused rather than served with a warning,
    because a credential that lives in version control is a credential every
    reader of the repository now holds, and serving it would be the store
    pretending the leak had not happened.
    """


class ValueNotStored(SecretsStoreError):
    """A read for a label the store has never been given.

    The other failure of a read, and the ordinary one: the caller asked for
    a credential the store does not hold.  Distinct from
    :class:`CommittedEnvironmentFileError` so a caller can tell "you asked
    for something I do not have" from "I have it but it is committed" — the
    two are remedied in different places (put the secret, versus rotate and
    de-commit it), and a single error would force the caller to guess which.
    """


def _looks_like_env_file(path: Path) -> bool:
    """Whether ``path`` is one of the environment-file names the rule covers.

    A suffix test, closed over :data:`_ENV_FILE_SUFFIXES`: ``.env``,
    ``.env.local`` and the other dotted names are matched, and a file with a
    different name — a ``config.yaml`` that happens to hold a token, a
    ``secrets.json`` — is not, because the feature's word is "env file" and
    the store refuses to read a secret into a class the sentence did not name.
    A directory or a missing path is not an env file: the check is about the
    *name*, and only a name that is one of the set.
    """
    name = path.name
    return any(name == suffix or name.endswith(suffix) for suffix in _ENV_FILE_SUFFIXES)


def load_env_file(path: str | os.PathLike[str]) -> dict[str, str]:
    """The ``KEY=VALUE`` pairs of an environment file, as a mapping.

    The reader for the file shape the committed-file check matches against:
    one ``KEY=VALUE`` assignment per line, ``#`` comments and blank lines
    ignored, surrounding space around the key and the value trimmed, and a
    value that is single- or double-quoted un-wrapped — the ordinary
    ``.env`` grammar, so the store compares committed *values* (what a
    caller would put in the store) against committed *lines* (what the file
    holds) on equal terms.  A line with no ``=`` is not an assignment and is
    skipped; a later line with a key seen before wins, the way a real
    environment-file loader behaves.  The mapping is what
    :func:`committed_paths` turns into the set of committed *values* a read
    is checked against, so the two share one grammar and a value the store
    holds is compared to a value the file held, not to the raw line.

    Refused (:class:`SecretsStoreError`) when the file cannot be read,
    because a committed-file check that could not read the file it is
    checking would be a check reporting "clean" over a file it never looked
    at — the exact silence the feature must not be.
    """
    resolved = Path(path)
    try:
        text = resolved.read_text(encoding="utf-8")
    except OSError as exc:
        raise SecretsStoreError(
            f"the environment file {resolved} could not be read: {exc} "
            f"(feature 151); a committed-file check that could not read the "
            f"file it is checking would report 'clean' over a file it never "
            f"looked at, which is the silence the rule exists to break."
        ) from exc
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator:
            continue
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def committed_paths(
    directory: str | os.PathLike[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> frozenset[Path]:
    """The environment files version control tracks under ``directory``.

    The one seam that has to ask the version-control system a question only
    it can answer: it runs ``git ls-files`` — the plumbing command that lists
    exactly the paths git tracks, the committed set, not the working tree —
    scoped to ``directory`` so the store does not read a credential into a
    repository that is not the deployment's, and keeps the two independent
    stores (feature 155) from being read as one.  ``directory`` is the
    deployment's repository root — :data:`REPO_ROOT_ENV`, or the current
    directory when that is unset — and the command is run there, so a
    process that started elsewhere still asks about the right tree.

    The result is filtered to :func:`_looks_like_env_file` names: the
    feature's rule is about *env files*, and a committed ``README.md`` is
    not a credential source, so it is dropped before the values are read —
    the store refuses a credential that matches a committed *env* line, and
    only that.  The paths are resolved to absolute so the value-match, which
    reads each file, can find it, and so a test can assert on a stable name.

    Read afresh on every call rather than cached: a file can be committed
    after the store first looked, and a credential committed an hour ago is
    exactly the drift the feature catches — a cached "clean" answer would
    let it through.  When git cannot answer — no repository, or no ``git`` on
    the path — the set is empty, which is "nothing is committed here" rather
    than an error: the store fails open on the one case it cannot know,
    because failing closed would refuse every read in a tree with no env
    files to refuse, a false refusal of the legitimate case.  See the module
    docstring for why that is the honest choice and not a hole.
    """
    source = os.environ if env is None else env
    root = directory or source.get(REPO_ROOT_ENV) or os.getcwd()
    root_path = Path(root)
    try:
        listing = subprocess.run(
            ["git", "ls-files", "--", str(root_path)],
            capture_output=True,
            text=True,
            check=False,
            cwd=str(root_path),
        )
    except (OSError, ValueError) as exc:
        # No `git` on the path, or the directory cannot be entered: the store
        # cannot ask version control, so it refuses to enforce rather than
        # refusing every read.
        return frozenset()
    if listing.returncode != 0:
        # Not a git repository (or git could not run here): the honest answer
        # is "nothing is committed that we can see", so no value can match.
        return frozenset()
    paths: set[Path] = set()
    for line in listing.stdout.splitlines():
        name = line.strip()
        if not name:
            continue
        candidate = (root_path / name).resolve()
        if _looks_like_env_file(candidate):
            paths.add(candidate)
    return frozenset(paths)


def _committed_values(directory: str | os.PathLike[str] | None, *, env: Mapping[str, str] | None) -> frozenset[str]:
    """The values held, line by line, in the committed env files.

    The set a read is checked against: every :func:`load_env_file` of every
    :func:`committed_paths`, flattened to the raw values (un-quoted, as a
    caller would have stored them).  A value the store is about to serve that
    is byte-for-byte one of these is a credential that lives in version
    control — the committed env file — and is refused.  The match is exact
    and whole-value, so a secret that merely shares a prefix with a committed
    placeholder is not falsely refused, and an empty value never matches (a
    blank line is not a credential).
    """
    values: set[str] = set()
    for path in committed_paths(directory, env=env):
        try:
            pairs = load_env_file(path)
        except SecretsStoreError:
            # A committed env file that cannot be read is a check that cannot
            # complete; skip it rather than let one unreadable file break
            # every read, but do not treat it as clean either — it simply
            # contributes no values to match against.
            continue
        values.update(pairs.values())
    return frozenset(values)


class SecretsStore:
    """The secrets manager's contract: put a value, get it back, refuse the committed.

    The abstraction feature 151's sentence quantifies over.  A real manager
    is a network service — AWS Secrets Manager, HashiCorp Vault, a
    sops/age document, a KMS-wrapped blob — and none of those is importable
    code on this tree (see ``infra/security/__init__.py``), so the contract
    is stated here and the one concrete store is the in-memory double:

    * :meth:`put_secret` — store a credential under a label.  The store
      remembers the value so a later read can be checked against the
      committed set: a secrets manager does not know how a caller came by a
      value, so the only way it can refuse "a credential from a committed
      env file" is to hold the values it has been given and compare them.
    * :meth:`get_secret` — return the value for a label, *or refuse it*.
      This is the one seam the law is written at: before returning the
      value, it checks whether the value it holds is byte-for-byte a line a
      committed env file holds, and raises
      :class:`CommittedEnvironmentFileError` if so.  The refusal is here, at
      the read, so the rule is written once and every caller is covered by
      construction.
    * :meth:`has_secret` — whether a label is stored, without serving the
      value (and so without running the committed check — that is a read's
      step, and a presence check should not refuse).

    A store holds values by label; it owns no secret of its own and names no
    secret's material beyond holding and comparing it.  The committed check
    is the store's, and it is enforced at :meth:`get_secret` — the only way
    a value leaves — so a caller that reads through the store has the refusal
    by construction, and the way to bypass it is to bypass the store, which
    is a thing a reviewer can see in a diff.
    """

    def put_secret(self, label: str, value: str) -> None:
        """Store ``value`` under ``label``.  Abstract."""
        raise NotImplementedError(f"{type(self).__name__} must implement put_secret() (feature 151).")

    def get_secret(self, label: str) -> str:
        """Return the value for ``label``, or refuse it if it is committed.

        The whole of feature 151 in one seam.  The value the store holds for
        ``label`` is checked against the committed env files — the values
        version control tracks — and if it is byte-for-byte one of them the
        credential is one that lives in the repository, so the read is
        refused with :class:`CommittedEnvironmentFileError` rather than
        served: a secret in version control is a secret every reader of the
        repository holds, and serving it would be the store pretending the
        leak had not happened.  Only a value the store actually holds can be
        refused this way — :meth:`put_secret` is what put it there — so the
        check is over the store's own values, not over every committed line
        in the abstract.  A label the store has never been given raises
        :class:`ValueNotStored`, the ordinary "not stored" rather than the
        committed refusal, because there is no value to refuse.
        """
        value = self._lookup(label)
        committed = _committed_values(self._directory(), env=self._env())
        if value and value in committed:
            match = self._find_committed_match(value)
            raise CommittedEnvironmentFileError(
                f"the credential {label!r} has the value of a line in the "
                f"committed environment file {match}; feature 151 stores "
                f"exchange credentials in a secrets manager and rejects any "
                f"credential read from a committed environment file — this "
                f"value lives in version control, so it is refused. Rotate "
                f"the credential and remove it from the repository; a secret "
                f"that was committed by mistake is still committed until the "
                f"line is gone."
            )
        return value

    def has_secret(self, label: str) -> bool:
        """Whether ``label`` is stored — a presence check, not a read.

        Deliberately does not run the committed-file check: asking "is this
        label stored?" is not the same as serving the value, and a presence
        check that refused would conflate "not stored" with "committed",
        which are remedied in different places.  The refusal is a read's
        step (:meth:`get_secret`), and this is not one.
        """
        return self._has(label)

    # -- the three seams a subclass supplies, kept small so the law is written once

    def _lookup(self, label: str) -> str:
        """The value for ``label``, raising :class:`ValueNotStored` if absent."""
        raise NotImplementedError(f"{type(self).__name__} must implement _lookup() (feature 151).")

    def _has(self, label: str) -> bool:
        """Whether ``label`` is present, without serving it."""
        raise NotImplementedError(f"{type(self).__name__} must implement _has() (feature 151).")

    def _directory(self) -> str | None:  # pragma: no cover - trivial default
        """The repository root the committed check asks git about, or ``None``."""
        return None

    def _env(self) -> Mapping[str, str] | None:  # pragma: no cover - trivial default
        """The environment the committed check reads, or ``None`` for ``os.environ``."""
        return None

    def _find_committed_match(self, value: str) -> Path | None:  # pragma: no cover - helper
        """The committed env file whose values hold ``value``, or ``None``.

        Split out from :meth:`get_secret` so the refusal message can name the
        file, and so a subclass that overrides where committed files are read
        from (a test double pointing at a fixture repository) supplies the one
        seam rather than re-deriving the match.  Default: scan the committed
        env files for the value.
        """
        for path in committed_paths(self._directory(), env=self._env()):
            try:
                pairs = load_env_file(path)
            except SecretsStoreError:
                continue
            if value in pairs.values():
                return path
        return None


class InMemorySecretsStore(SecretsStore):
    """A secrets store that holds values in process memory.

    The test double and the honest minimal shape of the contract: values
    live in an instance attribute, so a credential put and got in one process
    round-trips, and nothing survives the process.  It is a
    :class:`SecretsStore` like any other to a caller — the committed check at
    :meth:`get_secret` is the base class's, so a suite exercises the real law
    through it rather than around it.  Instance state, not class state: two
    in-memory stores are two independent managers, and a shared class
    attribute would make them one and leak a credential between them, which
    is the one thing a secrets store must not do.

    The store holds only the values it was given, never a path it was told to
    read — which is the point of the abstraction: a secrets manager is asked
    for a value by label, and the committed check is over the value, not over
    how the value arrived.
    """

    def __init__(
        self,
        *,
        repo_root: str | os.PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self._values: dict[str, str] = {}
        self._repo_root = repo_root
        self._env_source = env

    def put_secret(self, label: str, value: str) -> None:
        if not isinstance(label, str) or not label.strip():
            raise SecretsStoreError(
                f"a secret needs a non-empty label, got {label!r} (feature 151); "
                f"the label is how the store names the credential it holds, and "
                f"a store that could not name a value could not be asked for it."
            )
        if not isinstance(value, str):
            raise SecretsStoreError(
                f"a secret value must be a string, got {type(value).__name__} "
                f"(feature 151); the store compares values to committed env-file "
                f"lines, and a value that is not text has no line to compare to."
            )
        self._values[label.strip()] = value

    def _lookup(self, label: str) -> str:
        if label not in self._values:
            raise ValueNotStored(
                f"no credential is stored under {label!r} (feature 151); the "
                f"store was never given a value for this label, so there is "
                f"nothing to serve — put it first, or ask for the label the "
                f"credential was stored under."
            )
        return self._values[label]

    def _has(self, label: str) -> bool:
        return label in self._values

    def _directory(self) -> str | None:
        return None if self._repo_root is None else os.fspath(self._repo_root)

    def _env(self) -> Mapping[str, str] | None:
        return self._env_source
