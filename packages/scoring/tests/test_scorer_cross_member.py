"""The cross-member seam feature 265 closes — pinned against the real
sealed sidecar, not a stand-in.

The workspace contract is that **no member imports another**, and the
scorer process meets it the way every shared spelling is met: the sidecar
is duck-read behind the one ``assignment(node_id)`` seam the null oracle's
own target route documents, restated — never imported — and a suite like
this one is what keeps the restatement honest
(``packages/regime/tests/test_cross_member.py`` states the discipline for
that member's seams; the in-function import that costs one test when a
sibling is absent rather than the collection of the whole suite is that
file's remedy too, and this one's).

Feature 265 is the seam where the two members' halves of the §4.2 barrier
finally meet, and it is worth stating exactly which side owns what,
because the split is the feature's own sentence:

* **the null oracle member** owns the labels and their credential path —
  the AES-GCM envelope, the ``0o600``-in-``0o700`` file, the key
  reference grammar, the per-node assignment value and the UUID
  normalization every key is written under.
* **this member** owns the process that holds the key and the one number
  it lets out: prd §4.4's fraction, computed inside, answered as one bare
  ``float``.

Neither imports the other.  So what this file pins, from the data side,
is that the **real** sealed sidecar satisfies the surface the process
duck-reads: that a real :class:`~nulloracle.NullSidecar` answers the
per-node seam over real encrypted bytes, that the join this member
restates agrees with the oracle's own normalizer on every UUID spelling,
that the oracle's read failures (a wrong key, a leak of permissions)
arrive at this member's callers translated — this vocabulary, original
chained — and that the whole composition runs end to end: an environment
that names a sidecar composes a process that answers the rate.

Why the imports are inside the tests: a module-scope ``import
nulloracle`` would make this member's suite fail to collect wherever the
sibling member is absent, which is the outcome the contract's remedy
exists to avoid.  In a function, the absence costs one test, and that
test says what is missing.  The path insert is the same bootstrap every
member suite performs for *itself*, applied to a sibling, because the
member suites are not installed into each other's environments.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from conftest import (  # type: ignore[import-not-found] - suite-local
    NULL_ONE,
    NULL_TWO,
    REAL_ONE,
    REAL_TWO,
    UNHELD,
    StandInPick,
)
from scoring import NullPickRateError, NullPickScorer
from scoring._scorer import _canonical_node_id

REPO_ROOT = Path(__file__).resolve().parents[3]
NULLORACLE_SRC = REPO_ROOT / "packages" / "nulloracle" / "src"

#: A 32-byte AES-256 key as raw bytes — the form :class:`NullSidecar`
#: itself accepts for a process that already holds the material, and the
#: form this suite writes and reads the sealed file with.  The hex form
#: of the same bytes is what an environment's ``hex:`` key reference
#: spells, which is how :func:`test_resolve_composes_the_process` drives
#: the real credential path without a KMS.
_KEY = bytes(range(32))


def _nulloracle():
    """The null oracle member, imported in-function.

    ``importorskip`` rather than a bare import: a workspace without the
    sibling should lose this suite's tests and nothing else.
    """
    if str(NULLORACLE_SRC) not in sys.path:
        sys.path.insert(0, str(NULLORACLE_SRC))
    return pytest.importorskip(
        "nulloracle", reason="the null oracle member is not in this workspace"
    )


def _sealed_campaign(tmp_path: Path, labels: dict[str, bool]):
    """A real sidecar, really sealed, holding the fixture campaign.

    Written through the oracle's own atomic write — so the file on disk
    carries the ``0o600``-in-``0o700`` rule the read path checks, not a
    fixture's idea of it — and answered with the sidecar and the key it
    was sealed with, for a process that holds the right one.
    """
    nulloracle = _nulloracle()
    sidecar = nulloracle.NullSidecar(tmp_path / "null" / "sidecar.enc", _KEY)
    sidecar.write(
        {
            node: nulloracle.NullAssignment(node, bit, perm_seed=11)
            for node, bit in labels.items()
        }
    )
    return sidecar


_CAMPAIGN = {NULL_ONE: True, REAL_ONE: False, NULL_TWO: True, REAL_TWO: False}
_PICKS = [StandInPick(NULL_ONE), StandInPick(REAL_ONE),
          StandInPick(NULL_TWO), StandInPick(REAL_TWO)]


def test_the_real_sidecar_satisfies_the_process_s_seam(tmp_path: Path) -> None:
    # The duck-read contract, pinned against the real value: the process
    # constructed over a real NullSidecar — sealed bytes, mode-bit rule,
    # whole-file read per ask and all — answers the rate through the one
    # seam the oracle documents, and answers it exactly.  This is the
    # agreement the whole feature hangs off, and the member's own suite
    # could not pin it: a stand-in proves the contract, only the real
    # sidecar proves the contract is the right one.
    sidecar = _sealed_campaign(tmp_path, _CAMPAIGN)
    process = NullPickScorer(sidecar)
    assert process.null_pick_rate(_PICKS) == 0.5
    # And the clean sub-campaign over the same sealed file: a real 0.0,
    # measured over picks that were committed — never confused with the
    # empty ask's refusal, which is the law's own distinction.
    assert process.null_pick_rate([REAL_ONE, REAL_TWO]) == 0.0


def test_the_join_agrees_with_the_oracle_s_own_normalizer() -> None:
    # The UUID canonicalization is restated in this member, never
    # imported — so the restatement is pinned against the oracle's own
    # normalizer, spelling for spelling: plain, mixed case, braced and
    # urn forms all canonicalize identically on both sides of the member
    # boundary, which is what makes the join honest wherever the caller
    # came by the address.
    nulloracle = _nulloracle()
    assignment = pytest.importorskip(
        f"{nulloracle.__name__}.assignment",
        reason="the assignment module is not where its member keeps it",
    )
    for spelling in (
        NULL_ONE,
        NULL_ONE.upper(),
        "{" + NULL_ONE + "}",
        "urn:uuid:" + NULL_ONE,
    ):
        assert _canonical_node_id(spelling, spelling) == (
            assignment.normalize_node_id(spelling)
        )
    assert _canonical_node_id(NULL_ONE, NULL_ONE) == NULL_ONE


def test_an_unheld_pick_is_refused_over_the_real_seam(tmp_path: Path) -> None:
    # The refusal the law stakes its calibration on, over real sealed
    # bytes: a pick the file holds no entry for is unknown, not real, and
    # the refusal names that pick — the caller's own fact — while the
    # sidecar's other three entries stay as unread as the sealed file
    # keeps them.
    sidecar = _sealed_campaign(tmp_path, _CAMPAIGN)
    process = NullPickScorer(sidecar)
    with pytest.raises(NullPickRateError) as raised:
        process.null_pick_rate([*_PICKS, UNHELD])
    message = str(raised.value)
    assert UNHELD in message
    for held in (NULL_ONE, NULL_TWO, REAL_ONE, REAL_TWO):
        assert held not in message


def test_a_wrong_key_is_translated_at_the_seam(tmp_path: Path) -> None:
    # The oracle's decryption refusal (a key that does not open the file)
    # must reach this member's callers as *this* member's vocabulary with
    # the original chained — the translation law every cross-member seam
    # states, because a caller's single ``except ScoringError`` must catch
    # the whole member and the oracle's types escaping through this seam
    # would defeat it.  Pinned by name as well as isinstance: the sidecar
    # was built by this suite's canonical import, so the class object is
    # one and the same here.
    nulloracle = _nulloracle()
    sidecar = _sealed_campaign(tmp_path, _CAMPAIGN)
    wrong = NullPickScorer(
        nulloracle.NullSidecar(sidecar.path, bytes(range(32, 64)))
    )
    with pytest.raises(NullPickRateError) as raised:
        wrong.null_pick_rate(_PICKS)
    assert "could not be read" in str(raised.value)
    cause = raised.value.__cause__
    assert cause is not None
    assert type(cause).__name__ == "SidecarDecryptionError"
    errors = pytest.importorskip(
        f"{nulloracle.__name__}.errors",
        reason="the error module is not where its member keeps it",
    )
    assert isinstance(cause, errors.SidecarDecryptionError)


def test_wide_open_permissions_are_translated_at_the_seam(
    tmp_path: Path,
) -> None:
    # The oracle's leak refusal (mode bits that admit a second account)
    # arrives translated the same way — and this failure is the one §7
    # says silently voids every calibration number, so the seam must not
    # swallow it into a rate either: no partial value, no zero, one named
    # refusal with the original underneath.
    sidecar = _sealed_campaign(tmp_path, _CAMPAIGN)
    os.chmod(sidecar.path, 0o644)  # the leak: group may read the labels
    process = NullPickScorer(sidecar)
    with pytest.raises(NullPickRateError) as raised:
        process.null_pick_rate(_PICKS)
    cause = raised.value.__cause__
    assert cause is not None
    assert type(cause).__name__ == "SidecarAccessError"


def test_resolve_composes_the_process_for_a_configured_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The whole credential path, end to end: the environment names the
    # file and the key (a ``hex:`` reference — the inline form, so the
    # path needs no KMS to test), and this member's resolve composes the
    # process by delegating to the oracle's own resolution — the
    # importlib-at-call-time reach, answering the real sidecar's real
    # rate.  The direct call and the builder agree, which is the
    # composition contract the component suite pins from the other side.
    import scoring as member

    sidecar = _sealed_campaign(tmp_path, _CAMPAIGN)
    monkeypatch.setenv("NULL_SIDECAR_PATH", str(sidecar.path))
    monkeypatch.setenv("NULL_SIDECAR_KEY_REF", "hex:" + _KEY.hex())
    process = NullPickScorer.resolve()
    assert process is not None
    assert process.null_pick_rate(_PICKS) == 0.5
    built = member.build_null_pick_scorer()
    assert built is not None
    assert built.null_pick_rate(_PICKS) == 0.5


def test_the_composed_application_carries_the_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The integration the app namespace exists for: a deployment that
    # names its sidecar composes, through the factory's scan, an
    # application whose ``scoring-null-pick-rate`` component is a process
    # that answers the rate — reached here through the seat, the way a
    # member that needs β₂ reaches it without importing this one.
    from app.module_loader import create_app
    from app.modules.scoring import scorer as scorer_seat

    sidecar = _sealed_campaign(tmp_path, _CAMPAIGN)
    monkeypatch.setenv("NULL_SIDECAR_PATH", str(sidecar.path))
    monkeypatch.setenv("NULL_SIDECAR_KEY_REF", "hex:" + _KEY.hex())
    app = create_app()
    process = scorer_seat.null_pick_scorer_component(app)
    assert process is not None
    assert callable(getattr(process, "null_pick_rate", None))
    assert process.null_pick_rate(_PICKS) == 0.5
    # And the labels stayed in: the composed process answers the number,
    # and the answer's type is the barrier's whole spelling.
    assert type(process.null_pick_rate(_PICKS)) is float
