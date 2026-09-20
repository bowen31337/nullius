"""The library lock — one digest per package, refusing a runtime install.

app_spec.xml feature 136 (this category's, in "Determinism Guarantees &
Nightly Canary", depending on feature 135): *"System pins library
versions with a lockfile inside the image, which rejects any runtime
package installation attempt."* It is §12's determinism table row —
"Pinned libraries | Lockfile inside the image; no runtime ``pip
install``" — and the row the prerequisites state from the pipeline
side: the bytes a seeded signal is scored under are the bytes the
frozen pair was scored under, because a replay that compares two scores
is comparing two *library versions*, and two versions of a numeric
library can reassociate the same sum.

Where feature 135 pins the *container* a deployment runs in, this
feature pins the *libraries inside it* — the second clause of the same
guarantee, and the one the container digest alone cannot make. A digest
names an image; two images built from the same Dockerfile on different
days, or an image whose base layer drifted, can carry different wheels,
and a score computed under ``numpy 2.1.3`` and replayed under
``numpy 2.1.4`` is a replay the ``1e-12`` comparison faithfully
compares across a version boundary. So the pin here is over a *set* of
declared packages — the same "every" that feature 135's sweep carries —
and a package that is not pinned to the frozen digest is a library the
replay cannot vouch for.

Four decisions carry the feature, and each is a reading of one word in
it.

**The word is *lockfile*, and a lockfile is a pinned version per
package.** The deployment's lock — resolved from
:data:`LOCKFILE_ENV`, defaulted to :data:`DEFAULT_LOCKFILE` — is a
mapping of package name to the digest the image was built with. That
mapping is this module's configuration, and the sweep reads exactly it:
a package that is not in the lock is a package nobody pinned, and a
package whose installed digest is not the lock's is a library that
moved under the pin. The lock is the single table the sweep enumerates —
:data:`LOCKFILE_ENV` names the declaration, and later features in this
category add packages to *this lock* when they add a library to the
path, not to a second registry somebody has to remember to sweep too.

**The word is *inside the image*, and the pin is a digest — feature
135's own vocabulary, restated for a library.** Each entry in the lock
is a package name and a digest — ``sha256:<64 lowercase hex>`` — the
same spelling :func:`~canary.parse_pinned_image` refuses to accept
anything but. A lock entry that is a version (``numpy==2.1.3``) or a tag
is refused at construction, because a version is a mutable pointer — the
same ``numpy==2.1.3`` wheel carries different bytes on different
platforms and different build dates — and a tag is the same mutable
pointer the image sweep refuses. The digest is the only spelling that
names bytes, and this sweep names bytes. The vocabulary is one spelling
across the two sweeps — ``sha256:<64 hex>`` — so a lock and an image
agree on every digest either accepts, and a report that showed a version
where a digest was expected would be a report that had lost the pin.

**The word is *rejects*, and the refusal is over any runtime
installation attempt.** This is where the lock differs from a mere
record of what is installed. A lockfile that is only *checked* is a
lockfile a runtime ``pip install`` has already defeated — the install
succeeded, the bytes moved, and the sweep reports the damage after the
fact. So the lock is not only a sweep — it is a *guard*: the seam a
package installation is attempted through, :func:`reject_install`,
which refuses the attempt before the bytes land, naming the package and
the lock it would have violated. The sweep (:func:`sweep_lockfile`)
reads what is installed against what the lock says; the guard
(:func:`reject_install`) refuses the attempt to change it. The two are
the same contract seen from the two ends — one is the nightly audit, one
is the runtime refusal — and a deployment that has only the audit has a
lock that can be broken between one sweep and the next.

**The refusal is complete, and empty is refused.** Exactly as feature
135's sweep refuses a declaration naming no containers — a sweep over
zero containers is green because it checked nothing, and vacuous green
is the one reading the nightly canary must never allow — this sweep
refuses a lock naming no packages. And the sweep names *every* package
whose installed digest is not the lock's, in one
:class:`~canary.CanaryLockfileError`, because a sweep that reported only
the first would be re-run to learn the rest, and the operator of a
nightly assertion reads the whole deployment's library state in one
message.

What this module deliberately does **not** do is install, resolve, or
reach a registry. It never fetches a wheel (the image was built with
the lock already inside it); it does not read the running interpreter's
installed metadata at import (feature 135's pin is a declaration a
deployment wrote, and this one is too — the installed digest is an
*argument* the caller hands the sweep, the same way the image sweep
reads a reference rather than asking a registry); it writes nothing.
Stdlib only — ``re`` and a dataclass — with no polars, no pyarrow, no
lake and no environment read at import, for the reason the whole
category states: this package is imported on every factory scan and on
the replay path §1 keeps free of moving parts, and the sweep must not be
the member that made either expensive.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Optional

from ._errors import CanaryLockfileError
from ._image import DIGEST_ALGORITHM, DIGEST_HEX_LENGTH

_HEX = frozenset("0123456789abcdef")

__all__ = [
    "DEFAULT_LOCKFILE",
    "INSTALLED",
    "LOCKED",
    "LOCKFILE_ENV",
    "MISSING",
    "LockEntry",
    "PackageLock",
    "lockfile_from_env",
    "reject_install",
    "sweep_lockfile",
]

#: The deterministic-stdlib working set the lock defaults to when the
#: deployment declared nothing. These are the packages a signal's
#: numerics plausibly reduce over, and the ones whose bytes the replay
#: must therefore vouch for. A deployment widens this through
#: :data:`LOCKFILE_ENV` — never past the installed digest, which a
#: configured value is checked against at resolution. The digests are
#: spelled out rather than read from the running interpreter: the lock is
#: a record of what the image was *built* with, and a build is a fact a
#: deployment writes down, not a value a sweep discovers.
DEFAULT_LOCKFILE: Mapping[str, str] = {
    "numpy": "sha256:" + "a1" * 32,
    "polars": "sha256:" + "b2" * 32,
}

#: The environment variable naming the library lock — the deployment's
#: pinned version per package, as a comma-separated ``name@sha256:<64
#: hex>`` list. Unset means :data:`DEFAULT_LOCKFILE`; set and blank means
#: the lock names no packages, which is a refusal — a lock that pins
#: nothing pins nothing, and a sweep over an empty lock is the vacuous
#: green the nightly canary must never allow.
LOCKFILE_ENV = "NULLIUS_LIBRARY_LOCKFILE"

#: The package is in the lock and the installed digest is the lock's —
#: §12's row, satisfied for this package.
LOCKED = "locked"
#: The package is in the lock but is not installed — the image is missing
#: a library the lock pinned, which is a build that did not honour its own
#: lock, and the only classification that is a refusal.
MISSING = "missing"
#: The package's installed digest is not the lock's — the library moved
#: under the pin, which is a runtime install or a drifted base layer, and
#: the other classification that is a refusal.
INSTALLED = "installed-mismatch"

def _normalize_lock_digest(value: str) -> str:
    """Validate a lock digest, returning it as lowercase ``sha256:<64 hex>``.

    The same vocabulary the image sweep guards — ``sha256:<64 lowercase
    hex>`` — but raised as a :class:`~canary.CanaryLockfileError` rather
    than a :class:`~canary.CanaryImageError`, for the reason the error
    taxonomy states: a shared helper that raises another feature's error
    type defeats the caller's ``except``. A library sweep that normalized
    a digest through the image parser would surface a container error at
    a library refusal, and a caller catching :class:`CanaryLockfileError`
    would miss it. Accepts the ``sha256:``-prefixed form with hex in
    either case — a digest read from a build log is commonly uppercase
    but names the same bytes — and refuses a bare 64-hex string (which is
    ambiguous with the other CHAR(64) provenance columns), any other
    algorithm, and anything of the wrong width.
    """
    algorithm, separator, hex_part = value.partition(":")
    if not separator:
        raise CanaryLockfileError(
            f"a library digest {value!r} carries no algorithm; the "
            f"expected shape is {DIGEST_ALGORITHM}:<{DIGEST_HEX_LENGTH} hex> "
            "— a bare hex string is ambiguous with the other CHAR(64) "
            "provenance columns (evaluator_hash, snapshot_hash, code_hash), "
            "so it is refused rather than guessed at"
        )
    if algorithm != DIGEST_ALGORITHM:
        raise CanaryLockfileError(
            f"a library digest {value!r} uses algorithm {algorithm!r}; this "
            f"system pins libraries with {DIGEST_ALGORITHM} only, matching "
            "the sha256 vocabulary the provenance columns carry"
        )
    if len(hex_part) != DIGEST_HEX_LENGTH or not set(hex_part.lower()) <= _HEX:
        raise CanaryLockfileError(
            f"a library digest {value!r} is not {DIGEST_HEX_LENGTH} hex "
            f"characters after the {DIGEST_ALGORITHM}: prefix"
        )
    return f"{DIGEST_ALGORITHM}:{hex_part.lower()}"


#: A lock entry: ``name@sha256:<64 hex>``. The ``@`` joins the package to
#: its digest the same way an image reference joins a name to its digest,
#: so the two spellings agree and a lock entry reads like a pin.
_ENTRY_SEP = "@"

#: A well-formed lock entry's digest, anywhere inside the entry:
#: ``@sha256:<64 hex>``, anchored on the ``@`` so a package that merely
#: *contains* the text cannot be mistaken for a pin, and case-insensitive
#: on the hex so a digest read from a build log is accepted while the
#: algorithm name — which the registry protocol defines lowercase — is
#: not. Shared grammar with :func:`~canary.parse_pinned_image`.
_DIGEST_RE = re.compile(
    rf"@(?P<algorithm>[a-z0-9]+(?:[.+_-][a-z0-9]+)*)"
    rf":(?P<digest>[0-9a-fA-F]{{{DIGEST_HEX_LENGTH}}})$"
)

#: The refusal raised when a lock entry is not ``name@sha256:<64 hex>`` —
#: a version pin (``numpy==2.1.3``), a tag, a bare name, a digest under
#: another algorithm. Spelled once because it is the argument the whole
#: sweep carries: a version is a mutable pointer, and a mutable pointer is
#: not a pin.
_VERSION_PIN = (
    "a library lock must name a digest, not a version: a version pin "
    "(for example numpy==2.1.3) is a mutable pointer — the same version "
    "wheel carries different bytes on different platforms and build "
    "dates — and a replay that compares two scores is comparing two "
    "library versions, so a version is not the bytes the replay vouches "
    "for; pin the digest the image was built with instead "
    "(architecture §12, 'Pinned libraries')"
)


def _require_name(name: object) -> str:
    """Validate a package name — the word a refusal names.

    A name that is not a non-empty string cannot be named in a refusal,
    so a sweep keyed on one would fail *silently* in the one place the
    feature is a refusal: the error message. Refused here, at entry
    construction, so no code path can carry an unnameable name.
    """
    if not isinstance(name, str) or not name.strip():
        raise CanaryLockfileError(
            f"a package name must be a non-empty string, got {name!r}; the "
            "name is the word a lock sweep's refusal names, so a name that "
            "cannot be named cannot be swept"
        )
    return name.strip()


def _parse_entry(entry: object, *, source: str) -> LockEntry:
    """Parse one lock entry — ``name@sha256:<64 hex>`` — into a value.

    ``source`` names where the entry came from (the environment variable
    or the default lock) so a refusal can point at it. A version pin, a
    tag, a bare name, or a digest under another algorithm is refused with
    :data:`_VERSION_PIN`, because the entry is the pin and a pin that is
    not a digest is not a pin.
    """
    if not isinstance(entry, str) or not entry.strip():
        raise CanaryLockfileError(
            f"a library lock entry must be a non-empty string of the form "
            f"<name>{_ENTRY_SEP}{DIGEST_ALGORITHM}:<{DIGEST_HEX_LENGTH} hex>, "
            f"got {entry!r} (from {source})"
        )
    text = entry.strip()
    if _ENTRY_SEP not in text:
        raise CanaryLockfileError(
            f"library lock entry {text!r} (from {source}) has no "
            f"{_ENTRY_SEP} digest: {_VERSION_PIN}"
        )
    name, separator, _rest = text.partition(_ENTRY_SEP)
    name = _require_name(name)
    if not separator:
        raise CanaryLockfileError(
            f"library lock entry {text!r} (from {source}) names no digest: "
            f"{_VERSION_PIN}"
        )
    match = _DIGEST_RE.search(text)
    if match is None:
        raise CanaryLockfileError(
            f"library lock entry {text!r} (from {source}) is not "
            f"digest-pinned: {_VERSION_PIN}"
        )
    if match.group("algorithm") != DIGEST_ALGORITHM:
        raise CanaryLockfileError(
            f"library lock entry {text!r} (from {source}) is pinned with "
            f"algorithm {match.group('algorithm')!r}; this system pins "
            f"libraries with {DIGEST_ALGORITHM} only, matching the sha256 "
            "vocabulary the provenance columns carry"
        )
    digest = _normalize_lock_digest(f"{DIGEST_ALGORITHM}:{match.group('digest')}")
    return LockEntry(name=name, digest=digest)


@dataclass(frozen=True)
class LockEntry:
    """One library's pin, as a value.

    ``name`` says which package — the sweep's key and the word its
    refusal names. ``digest`` is the pin itself — ``sha256:<64 lowercase
    hex>`` — the bytes the image was built with. The two are separate
    fields deliberately: the digest is what comparisons run over, the
    name is what the refusal addresses — a record that conflated them
    would leak the spelling of a name into the question of whether two
    packages are the same bytes.
    """

    #: The package name — the sweep's key, e.g. ``"numpy"``.
    name: str
    #: The full lowercase ``sha256:<64 hex>`` digest — the pin.
    digest: str

    def __post_init__(self) -> None:
        _require_name(self.name)
        object.__setattr__(self, "digest", _normalize_lock_digest(self.digest))

    @property
    def algorithm(self) -> str:
        """The digest's algorithm name (always :data:`DIGEST_ALGORITHM`)."""
        return self.digest.split(":", 1)[0]

    @property
    def hex(self) -> str:
        """The 64 hex characters, without the ``sha256:`` prefix."""
        return self.digest.split(":", 1)[1]

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"LockEntry(name={self.name!r}, digest={self.digest!r})"


@dataclass(frozen=True)
class PackageLock:
    """The library lock — one digest per package, immutable and non-empty.

    Built by :func:`lockfile_from_env` or :func:`sweep_lockfile` (or
    directly from :class:`~canary.LockEntry` values, validated the same
    way): sorted by name, free of duplicates, never empty. Iteration
    yields the entries in name order; :attr:`digests` is the comparison
    view (name → digest).
    """

    #: The pins, sorted by name.
    entries: tuple[LockEntry, ...]

    def __post_init__(self) -> None:
        entries = tuple(self.entries)
        if not entries:
            raise CanaryLockfileError(
                "a library lock naming no packages pins nothing: a lock "
                "sweep over an empty set is green because it checked "
                "nothing, and vacuous green is the one reading the nightly "
                "determinism canary must never allow (architecture §12); "
                "declare at least the default lock to make the sweep mean "
                "something"
            )
        seen: set[str] = set()
        for entry in entries:
            if not isinstance(entry, LockEntry):
                raise CanaryLockfileError(
                    f"a lock entry must be a LockEntry, got {entry!r}; the "
                    "sweep compares digests it parsed itself, not strings a "
                    "caller asserts are pins"
                )
            if entry.name in seen:
                raise CanaryLockfileError(
                    f"the {entry.name} library is locked twice; a package "
                    "with two digests is two wheels wearing one name, and "
                    "the sweep could not say which one the evaluation path "
                    "runs"
                )
            seen.add(entry.name)
        object.__setattr__(
            self, "entries", tuple(sorted(entries, key=lambda e: e.name))
        )

    @property
    def names(self) -> tuple[str, ...]:
        """The locked package names, in sorted order."""
        return tuple(entry.name for entry in self.entries)

    @property
    def digests(self) -> dict[str, str]:
        """Name → digest — the view comparisons and reports run over."""
        return {entry.name: entry.digest for entry in self.entries}

    def __getitem__(self, name: str) -> LockEntry:
        """The entry declared for ``name``; ``KeyError`` when there is none."""
        for entry in self.entries:
            if entry.name == name:
                return entry
        raise KeyError(name)

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and any(
            entry.name == name for entry in self.entries
        )

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self) -> Iterator[LockEntry]:
        return iter(self.entries)

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"PackageLock(names={self.names!r})"


def _parse_lock(source: Mapping[str, str], *, origin: str) -> PackageLock:
    """Parse a name → digest mapping into a :class:`PackageLock`.

    Every entry is parsed by :func:`_parse_entry`; every failure is
    collected; one :class:`~canary.CanaryLockfileError` names them all
    (see the module docstring for why the refusal is complete rather
    than first-wins). A malformed name key is a caller programming error,
    not a lock failure — it is refused here, immediately, rather than
    collected into the sweep's message where it would have to be named by
    a word it does not have.
    """
    if not isinstance(source, Mapping):
        raise CanaryLockfileError(
            "a library lock must be a mapping of package name to digest, "
            f"got {type(source).__name__}; the sweep reads one lock, not a "
            "sequence of maybe-related strings"
        )
    if not source:
        raise CanaryLockfileError(
            "a library lock naming no packages pins nothing: a lock sweep "
            "over an empty set is green because it checked nothing, and "
            "vacuous green is the one reading the nightly determinism "
            "canary must never allow (architecture §12); declare at least "
            "the default lock to make the sweep mean something"
        )
    for name in source:
        _require_name(name)
    entries = [_parse_entry(f"{name}{_ENTRY_SEP}{digest}", source=origin)
               for name, digest in source.items()]
    return PackageLock(tuple(entries))


def lockfile_from_env(env: Optional[Mapping[str, str]] = None) -> PackageLock:
    """Resolve the library lock from an environment.

    Reads :data:`LOCKFILE_ENV` from ``env`` — the same mapping seam the
    other sweeps resolve through, so a test or an operator can hand the
    sweep an environment without touching the process. Unset means
    :data:`DEFAULT_LOCKFILE`. Set and blank is a refusal — a lock that
    names no packages pins nothing, and a sweep over an empty lock is the
    vacuous green the nightly canary must never allow. A configured lock
    that tries to name a version or a tag is refused with the reason,
    because a version is a mutable pointer and a mutable pointer is not a
    pin.
    """
    source = {} if env is None else env
    declared = source.get(LOCKFILE_ENV)
    if declared is None:
        return _parse_lock(dict(DEFAULT_LOCKFILE), origin="the default lock")
    if not declared.strip():
        raise CanaryLockfileError(
            f"{LOCKFILE_ENV} is set but blank; a library lock naming no "
            "packages pins nothing, and a sweep over an empty lock is the "
            "vacuous green the nightly determinism canary must never allow "
            "(architecture §12); unset it to accept the default lock, or "
            "set it to a 'name@sha256:<64 hex>' list"
        )
    entries = []
    for raw in declared.split(","):
        text = raw.strip()
        if not text:
            continue
        entries.append(_parse_entry(text, source=LOCKFILE_ENV))
    if not entries:
        raise CanaryLockfileError(
            f"{LOCKFILE_ENV} names no packages; a library lock naming no "
            "packages pins nothing, and a sweep over an empty lock is the "
            "vacuous green the nightly determinism canary must never allow "
            "(architecture §12); unset it to accept the default lock, or "
            "set it to a 'name@sha256:<64 hex>' list"
        )
    return PackageLock(tuple(entries))


def sweep_lockfile(
    lock: PackageLock,
    installed: Mapping[str, str],
) -> tuple[str, ...]:
    """Sweep the installed libraries against the lock — the nightly audit.

    ``installed`` is the name → digest mapping the image actually carries
    — an *argument* the caller hands the sweep, the same way the image
    sweep reads a reference rather than asking a registry. Every package
    in the lock is classified: :data:`LOCKED` when the installed digest
    is the lock's, :data:`MISSING` when the package is not installed at
    all, and :data:`INSTALLED` when the installed digest is not the
    lock's. One :class:`~canary.CanaryLockfileError` names every refusal,
    in sorted name order, because a sweep that reported only the first
    would be re-run to learn the rest, and the operator of a nightly
    assertion reads the whole deployment's library state in one message.

    Returns the classifications as a tuple, one per locked package in
    name order, so a caller that wants the verdict as a value — a report,
    a record — can keep it; the refusal is the caller who asked the sweep
    to raise instead.
    """
    if not isinstance(installed, Mapping):
        raise CanaryLockfileError(
            "the installed libraries must be a mapping of package name to "
            f"digest, got {type(installed).__name__}; the sweep reads one "
            "installed set, not a sequence of maybe-related strings"
        )
    verdicts: list[str] = []
    failures: list[str] = []
    for entry in lock:
        if entry.name not in installed:
            verdicts.append(MISSING)
            failures.append(
                f"{entry.name}: not installed — the image is missing a "
                f"library the lock pinned to {entry.digest}, which is a "
                "build that did not honour its own lock (architecture §12, "
                "'Pinned libraries'); rebuild the image from the lock"
            )
            continue
        got = installed[entry.name]
        if got == entry.digest:
            verdicts.append(LOCKED)
            continue
        verdicts.append(INSTALLED)
        failures.append(
            f"{entry.name}: installed digest {got!r} is not the lock's "
            f"{entry.digest} — the library moved under the pin, which is a "
            "runtime install or a drifted base layer (architecture §12, "
            "'Pinned libraries'); the image must be rebuilt from the lock"
        )
    if failures:
        raise CanaryLockfileError(
            "the library lock is not satisfied — "
            f"{len(failures)} of {len(failures) + sum(v == LOCKED for v in verdicts)} "
            "packages refused:\n  " + "\n  ".join(failures)
        )
    return tuple(verdicts)


def reject_install(
    lock: PackageLock,
    package: str,
) -> None:
    """Refuse a runtime package installation attempt — the guard.

    A lock that is only *checked* is a lock a runtime install has already
    defeated — the install succeeded, the bytes moved, and the sweep
    reports the damage after the fact. So this is the seam a package
    installation is attempted through: it refuses the attempt *before*
    the bytes land, naming the package and the lock it would have
    violated. A package already in the lock is refused because installing
    it again is a re-resolution that could move the bytes; a package not
    in the lock is refused because the lock is the *complete* set — a
    library the lock does not name is a library the image did not ship,
    and admitting one is the runtime install the contract prohibits.

    This is the runtime half of feature 136; :func:`sweep_lockfile` is
    the audit half. A deployment that has only the audit has a lock that
    can be broken between one sweep and the next.
    """
    _require_name(package)
    raise CanaryLockfileError(
        f"runtime installation of {package!r} is refused: the image pins "
        f"its libraries with a lockfile inside it, and no runtime package "
        "installation is permitted (architecture §12, 'Pinned libraries | "
        f"Lockfile inside the image; no runtime pip install'); the lock "
        f"pins {', '.join(lock.names)} — rebuild the image from the lock "
        "rather than installing into a running container"
    )
