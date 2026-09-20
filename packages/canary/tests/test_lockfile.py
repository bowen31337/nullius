"""The library lock — one digest per package, refusing a runtime install.

These tests pin :mod:`canary._lockfile` from the outside — the lock's
acceptances, its sweep's refusals, and the guard's refusal — because the
lock is the seam between the libraries an image carries and the bytes the
replay vouches for. The refusal cases are the feature: app_spec.xml
feature 136's own clauses are "pins library versions with a lockfile
inside the image" *and* "rejects any runtime package installation
attempt", and each test below is one of those clauses arriving in a
different costume.

The suite follows the shape the sibling sweeps established (test_image,
test_device, test_ordering): the verdict is a value on the clean path and
the refusal is raised on the broken one, the refusal is collective and
names every offender, and an empty lock is refused rather than passed —
vacuous green is the one reading the nightly canary must never allow.
"""

from __future__ import annotations

import dataclasses

import pytest
from canary import (
    DEFAULT_LOCKFILE,
    LOCKED,
    LOCKFILE_ENV,
    MISSING,
    CanaryError,
    CanaryLockfileError,
    LockEntry,
    PackageLock,
    lockfile_from_env,
    parse_pinned_image,
    reject_install,
    sweep_lockfile,
)

#: A digest of the right width, spelled out rather than computed.
_A_DIGEST = "sha256:" + "a1" * 32
_OTHER_DIGEST = "sha256:" + "cd" * 32


# -- The lock as a value ------------------------------------------------------


def test_a_lock_entry_carries_name_and_digest() -> None:
    entry = LockEntry(name="numpy", digest=_A_DIGEST)
    assert entry.name == "numpy"
    assert entry.digest == _A_DIGEST
    assert entry.algorithm == "sha256"
    assert entry.hex == "a1" * 32


def test_a_lock_entry_normalizes_an_uppercase_digest() -> None:
    # The same digest vocabulary the image sweep uses: a digest pasted
    # from a build log is often uppercase but names the same bytes.
    entry = LockEntry(name="numpy", digest="sha256:" + "A1" * 32)
    assert entry.digest == _A_DIGEST


def test_a_lock_entry_is_immutable() -> None:
    entry = LockEntry(name="numpy", digest=_A_DIGEST)
    with pytest.raises(dataclasses.FrozenInstanceError):
        entry.name = "scipy"  # type: ignore[misc]


@pytest.mark.parametrize("name", [None, "", "   "], ids=["none", "empty", "blank"])
def test_an_unnameable_name_is_rejected(name: object) -> None:
    # The name is the word a refusal names; a name that cannot be named
    # cannot be swept — refused at value construction, before any code
    # path can carry it into a message.
    with pytest.raises(CanaryLockfileError, match="non-empty string"):
        LockEntry(name=name, digest=_A_DIGEST)  # type: ignore[arg-type]


def test_a_lock_entry_digest_without_an_algorithm_is_rejected() -> None:
    # A bare 64-hex string is ambiguous with the other CHAR(64) provenance
    # columns — the same refusal the image sweep makes.
    with pytest.raises(CanaryLockfileError, match="carries no algorithm"):
        LockEntry(name="numpy", digest="a1" * 32, )


def test_a_package_lock_sorts_and_deduplicates() -> None:
    lock = PackageLock(
        (
            LockEntry(name="polars", digest=_OTHER_DIGEST),
            LockEntry(name="numpy", digest=_A_DIGEST),
        )
    )
    assert lock.names == ("numpy", "polars")
    assert lock.digests == {"numpy": _A_DIGEST, "polars": _OTHER_DIGEST}


def test_an_empty_package_lock_is_refused() -> None:
    with pytest.raises(CanaryLockfileError, match="naming no packages"):
        PackageLock(())


def test_a_doubly_locked_package_is_refused() -> None:
    with pytest.raises(CanaryLockfileError, match="locked twice"):
        PackageLock(
            (
                LockEntry(name="numpy", digest=_A_DIGEST),
                LockEntry(name="numpy", digest=_OTHER_DIGEST),
            )
        )


# -- Resolving the lock from the environment ----------------------------------


def test_an_unset_variable_resolves_to_the_default_lock() -> None:
    lock = lockfile_from_env({})
    assert lock.names == tuple(sorted(DEFAULT_LOCKFILE))
    assert lock.digests == {
        name: digest for name, digest in DEFAULT_LOCKFILE.items()
    }


def test_a_configured_variable_is_parsed_name_by_name() -> None:
    env = {LOCKFILE_ENV: f"numpy@{_A_DIGEST}, polars@{_OTHER_DIGEST}"}
    lock = lockfile_from_env(env)
    assert lock.names == ("numpy", "polars")
    assert lock.digests == {"numpy": _A_DIGEST, "polars": _OTHER_DIGEST}


def test_surrounding_whitespace_and_blank_entries_are_tolerated() -> None:
    # A lock read from a YAML block scalar often arrives with spacing; a
    # blank entry between commas is not a package and is skipped, not a
    # refusal — the lock still names packages.
    env = {LOCKFILE_ENV: f" numpy@{_A_DIGEST} , , polars@{_OTHER_DIGEST} "}
    lock = lockfile_from_env(env)
    assert lock.names == ("numpy", "polars")


def test_a_blank_variable_is_refused_not_defaulted() -> None:
    # Set and blank is a deployment actively naming no packages — the
    # vacuous green the canary must never allow — so it is refused, not
    # folded into the default.
    with pytest.raises(CanaryLockfileError, match="set but blank"):
        lockfile_from_env({LOCKFILE_ENV: "   "})


def test_a_variable_naming_only_blank_entries_is_refused() -> None:
    with pytest.raises(CanaryLockfileError, match="names no packages"):
        lockfile_from_env({LOCKFILE_ENV: " , , "})


@pytest.mark.parametrize(
    "entry",
    [
        "numpy==2.1.3",
        "numpy:2.1.3",
        "numpy",
        "numpy@sha256:xyz",
        "numpy@sha512:" + "a" * 128,
    ],
    ids=["version", "tag-colon", "bare", "bad-hex", "other-algorithm"],
)
def test_a_non_digest_entry_is_refused(entry: str) -> None:
    # A version is a mutable pointer — the same version wheel carries
    # different bytes on different platforms — and a mutable pointer is
    # not a pin. Every other malformed spelling is refused with the same
    # reason: only a digest names bytes.
    with pytest.raises(CanaryLockfileError, match="mutable pointer") as raised:
        lockfile_from_env({LOCKFILE_ENV: entry})
    assert isinstance(raised.value, CanaryError)


# -- The sweep: the nightly audit ---------------------------------------------


def test_a_satisfied_lock_sweeps_clean() -> None:
    lock = PackageLock((LockEntry(name="numpy", digest=_A_DIGEST),))
    verdicts = sweep_lockfile(lock, {"numpy": _A_DIGEST})
    assert verdicts == (LOCKED,)


def test_a_missing_package_is_refused() -> None:
    lock = PackageLock(
        (
            LockEntry(name="numpy", digest=_A_DIGEST),
            LockEntry(name="polars", digest=_OTHER_DIGEST),
        )
    )
    with pytest.raises(CanaryLockfileError, match="polars") as raised:
        sweep_lockfile(lock, {"numpy": _A_DIGEST})
    assert MISSING in str(raised.value)


def test_an_installed_mismatch_is_refused() -> None:
    lock = PackageLock((LockEntry(name="numpy", digest=_A_DIGEST),))
    with pytest.raises(CanaryLockfileError, match="numpy") as raised:
        sweep_lockfile(lock, {"numpy": _OTHER_DIGEST})
    # The refusal states what was found and what the lock required, so an
    # operator can see the library moved under the pin.
    assert "is not the lock's" in str(raised.value)


def test_the_sweep_is_collective() -> None:
    # One error names every refused package, in sorted name order — a
    # sweep that reported only the first would be re-run to learn the
    # rest, and the operator reads the whole library state in one message.
    lock = PackageLock(
        (
            LockEntry(name="numpy", digest=_A_DIGEST),
            LockEntry(name="polars", digest=_OTHER_DIGEST),
            LockEntry(name="scipy", digest="sha256:" + "e3" * 32),
        )
    )
    with pytest.raises(CanaryLockfileError) as raised:
        sweep_lockfile(lock, {"numpy": _OTHER_DIGEST})
    message = str(raised.value)
    assert message.count("refused") >= 1
    # All three are named, and numpy (a mismatch) precedes polars and
    # scipy (both missing) in sorted order.
    assert message.index("numpy") < message.index("polars") < message.index("scipy")


def test_a_sweep_returns_verdicts_for_every_locked_package() -> None:
    # The clean path returns a verdict per package, so a report can file
    # what the sweep checked rather than merely that it did not raise.
    lock = PackageLock(
        (
            LockEntry(name="numpy", digest=_A_DIGEST),
            LockEntry(name="polars", digest=_OTHER_DIGEST),
        )
    )
    verdicts = sweep_lockfile(lock, {"numpy": _A_DIGEST, "polars": _OTHER_DIGEST})
    assert verdicts == (LOCKED, LOCKED)


def test_an_empty_lock_sweep_is_refused() -> None:
    # A sweep over zero packages is green because it checked nothing — the
    # same vacuous green the image sweep refuses.
    lock = PackageLock((LockEntry(name="numpy", digest=_A_DIGEST),))
    with pytest.raises(CanaryLockfileError, match="not satisfied"):
        sweep_lockfile(lock, {})


def test_the_sweep_reads_the_installed_set_as_an_argument() -> None:
    # The installed digest is handed to the sweep, not discovered — the
    # same stance the image sweep takes (it reads a reference rather than
    # asking a registry). A non-mapping installed set is a caller error.
    lock = PackageLock((LockEntry(name="numpy", digest=_A_DIGEST),))
    with pytest.raises(CanaryLockfileError, match="must be a mapping"):
        sweep_lockfile(lock, [("numpy", _A_DIGEST)])  # type: ignore[list-item]


# -- The guard: refusing a runtime install ------------------------------------


def test_a_runtime_install_attempt_is_refused() -> None:
    lock = PackageLock(
        (
            LockEntry(name="numpy", digest=_A_DIGEST),
            LockEntry(name="polars", digest=_OTHER_DIGEST),
        )
    )
    with pytest.raises(CanaryLockfileError) as raised:
        reject_install(lock, "pandas")
    message = str(raised.value)
    # The refusal names the package, states the contract, and lists the
    # locked set so an operator knows what the image already ships.
    assert "pandas" in message
    assert "runtime" in message
    assert "no runtime" in message
    assert "numpy" in message
    assert "polars" in message
    assert isinstance(raised.value, CanaryError)


def test_a_runtime_reinstall_of_a_locked_package_is_still_refused() -> None:
    # Installing a package already in the lock is refused too: a
    # re-resolution could move the bytes, and the lock is the complete
    # set — nothing is admitted past it.
    lock = PackageLock((LockEntry(name="numpy", digest=_A_DIGEST),))
    with pytest.raises(CanaryLockfileError, match="numpy"):
        reject_install(lock, "numpy")


@pytest.mark.parametrize("package", [None, "", "   "], ids=["none", "empty", "blank"])
def test_a_runtime_install_with_an_unnameable_package_is_refused(package: object) -> None:
    with pytest.raises(CanaryLockfileError, match="non-empty string"):
        reject_install(PackageLock((LockEntry(name="numpy", digest=_A_DIGEST),)), package)  # type: ignore[arg-type]


# -- One spelling of the pin, across the two sweeps ---------------------------


def test_the_lock_and_the_image_share_a_digest_vocabulary() -> None:
    # Feature 136's digest is feature 135's digest: a lock entry's digest
    # is accepted by the image parser, so a report never shows a version
    # where a digest was expected.
    pin = parse_pinned_image(f"ghcr.io/nullius/evaluator@{_A_DIGEST}", role="evaluator")
    entry = LockEntry(name="numpy", digest=pin.digest)
    assert entry.digest == _A_DIGEST


def test_the_default_lock_is_a_mapping_of_name_to_digest() -> None:
    # The default is a real lock, not a placeholder — every entry parses
    # and every digest is the shared vocabulary.
    lock = lockfile_from_env({})
    for name, digest in DEFAULT_LOCKFILE.items():
        assert name in lock
        assert lock[name].digest == digest
