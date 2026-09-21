"""Feature 187 — the headline dreaming claim that rests on bootstrap worlds alone.

app_spec.xml, "Bootstrap Worlds", feature 187: *System rejects a headline
dreaming claim resting on bootstrap worlds alone, because bootstrap and
financial pools report separately.*  This suite holds the refusal to the
sentence the way the member's other suites hold theirs — clause by clause,
from the documented side:

* **"rejects a headline dreaming claim"** — :func:`rejects_dreaming_claim`
  is a judgment about a claim, made where the claim and both figures are
  visible.  It takes a :class:`~bootstrap.DreamingClaim` (the basis the
  claim rests on) and a :class:`~bootstrap.WorldCensus` (feature 186's two
  figures, held apart) and answers whether the claim rests on bootstrap
  worlds.  It renders no other verdict: a claim that rests on financial
  worlds may still be wrong, and that is the scorer's to find.
* **"resting on bootstrap worlds alone"** — a claim rests on bootstrap
  worlds when the financial figure the M3 gate reads falls short of the
  gate, yet the claim would proceed — either because it names the total as
  its basis or because the bootstrap half is what carries it over the gate.
  When ``n_financial`` meets the gate the claim stands on the pool the gate
  was meant to see, whatever basis it names.
* **"because bootstrap and financial pools report separately"** — the
  refusal is the exact inversion of §10.6's rule, and the two figures are
  the seam: the judgment reads the census's ``n_financial`` and ``total``
  and nothing else, and a claim that rests on the financial figure alone is
  never refused here — a thin financial claim is rejected by the gate for
  being thin, not by this feature for resting on the wrong pool.

Beside the clause-by-clause claims sit the judgment's own guards — the
claim that names no usable basis, the gate that is not a world count, the
object that is not a census — each pinned by the error it raises and the
subject it names, the discipline every store suite in this workspace
follows.
"""

from __future__ import annotations

import dataclasses

import pytest
from bootstrap import (
    FINANCIAL_BASIS,
    M3_GATE_WORLDS,
    TOTAL_BASIS,
    BootstrapPoolError,
    DreamingClaim,
    WorldCensus,
    claim_basis,
    rejects_dreaming_claim,
)

# -- The two bases, and the one figure each reads --------------------------------


def test_a_financial_claim_on_the_gate_figure_is_admitted() -> None:
    # A claim that rests on the financial world count the M3 gate reads is
    # judged on ``n_financial`` alone.  When it meets the gate the claim
    # stands on the pool the gate was meant to see, and the bootstrap half
    # is irrelevant to it — §10.6.1's *"pads n, never n_financial"* lets
    # the total rise without the gate moving.
    census = WorldCensus(n_financial=M3_GATE_WORLDS, n_bootstrap=45)
    assert rejects_dreaming_claim(DreamingClaim(FINANCIAL_BASIS), census) is False


def test_a_financial_claim_above_the_gate_is_admitted() -> None:
    # More financial worlds only strengthen the paired comparison, so there
    # is no upper edge — the gate is a floor the financial evidence must
    # reach, and a claim resting on a figure above it is admitted.
    census = WorldCensus(n_financial=M3_GATE_WORLDS + 20, n_bootstrap=45)
    assert rejects_dreaming_claim(DreamingClaim(FINANCIAL_BASIS), census) is False


def test_a_financial_claim_below_the_gate_fails_on_financial_grounds() -> None:
    # A financial claim whose figure is the gate's own count and falls
    # short is rejected by the gate for being thin — not by this feature.
    # It never leans on the bootstrap half (its figure *is* n_financial),
    # so it does not rest on bootstrap worlds and this judgment leaves it
    # to the gate.
    census = WorldCensus(n_financial=M3_GATE_WORLDS - 1, n_bootstrap=45)
    assert rejects_dreaming_claim(DreamingClaim(FINANCIAL_BASIS), census) is False


def test_a_total_claim_carried_over_the_gate_by_bootstrap_is_refused() -> None:
    # The precise inversion §10.6 and §10.6.1 name: the financial figure
    # the gate reads is short, but the claim rests on the ladder's sum and
    # the bootstrap half is what carries it over the gate.  1 financial
    # world and 60 bootstrap worlds is a total of 61 — above the gate — and
    # the only reason it clears is the bootstrap padding.
    census = WorldCensus(n_financial=1, n_bootstrap=60)
    assert census.total >= M3_GATE_WORLDS
    assert rejects_dreaming_claim(DreamingClaim(TOTAL_BASIS), census) is True


def test_a_total_claim_whose_financial_figure_clears_is_admitted() -> None:
    # A total-basis claim whose financial figure already meets the gate
    # does not rest on bootstrap worlds: it would proceed on the gate
    # figure alone, so the bootstrap half is irrelevant to it.  The refusal
    # is about which pool carries the claim, not about the basis it names.
    census = WorldCensus(n_financial=M3_GATE_WORLDS, n_bootstrap=45)
    assert rejects_dreaming_claim(DreamingClaim(TOTAL_BASIS), census) is False


def test_a_total_claim_thin_on_both_pools_fails_on_the_gate() -> None:
    # A total-basis claim whose sum is also short of the gate fails on the
    # gate regardless of which pool it counts — it is merely thin, not
    # resting on bootstrap worlds.  Left to the gate.
    census = WorldCensus(n_financial=1, n_bootstrap=5)
    assert census.total < M3_GATE_WORLDS
    assert rejects_dreaming_claim(DreamingClaim(TOTAL_BASIS), census) is False


def test_the_bare_dreaming_claim_the_feature_names_is_refused() -> None:
    # The common case the feature's sentence targets: a dreaming cycle that
    # asserts "we have enough worlds to dream" reaches for the ladder's
    # total, and the bootstrap pool is what carries it over the gate.  This
    # is the headline claim resting on bootstrap worlds alone.
    census = WorldCensus(n_financial=1, n_bootstrap=60)
    assert rejects_dreaming_claim(DreamingClaim(TOTAL_BASIS), census) is True


# -- The gate is a parameter, and a floor ----------------------------------------


def test_the_gate_is_the_default_the_feature_was_written_against() -> None:
    # §10.3.1's ``n > 53`` at the committed ``M`` and ``σ_V`` — the floor a
    # financial dreaming claim must meet.  The published default is the
    # judgment's own constant, so a rename on one side fails here.
    assert M3_GATE_WORLDS == 53


def test_a_deployment_gate_moves_the_floor() -> None:
    # A deployment that sets its own gate passes it as a keyword, and the
    # judgment moves with it.  The same claim and census, judged against
    # two floors: at gate 40 the financial evidence clears the floor, so
    # the claim stands on the pool the gate was meant to see and is
    # admitted; at gate 53 the financial figure falls short and only the
    # bootstrap-padded total clears it, so the claim is refused.  The floor
    # the financial evidence must reach is what moves.
    census = WorldCensus(n_financial=40, n_bootstrap=60)  # total 100
    assert rejects_dreaming_claim(DreamingClaim(TOTAL_BASIS), census, gate=40) is False
    assert rejects_dreaming_claim(DreamingClaim(TOTAL_BASIS), census, gate=53) is True
    # A gate above the total leaves both pools short — the claim is merely
    # thin, not resting on bootstrap worlds, and is left to the gate.
    assert rejects_dreaming_claim(DreamingClaim(TOTAL_BASIS), census, gate=101) is False


@pytest.mark.parametrize("bad", [-1, True, "53", 53.0, None])
def test_a_gate_that_is_not_a_world_count_is_refused(bad: object) -> None:
    # A gate that is not a non-negative whole number cannot judge a
    # dreaming cycle: it would silently admit or block a cycle on a number
    # that is not a world count.  ``True`` is refused where a count
    # belongs for the reason the census refuses one on a figure.
    census = WorldCensus(n_financial=1, n_bootstrap=60)
    with pytest.raises(BootstrapPoolError, match="world count"):
        rejects_dreaming_claim(DreamingClaim(TOTAL_BASIS), census, gate=bad)  # type: ignore[arg-type]


# -- The claim is duck-typed, and its basis is the seam ----------------------------


class _BareClaim:
    """A claim that is not a DreamingClaim but carries the surface judged."""

    def __init__(self, basis: str) -> None:
        self.basis = basis


def test_a_claim_is_read_duck_typed_on_its_basis() -> None:
    # The module loader hands out a second copy of every class under a
    # synthetic name, so the judgment duck-types the claim rather than
    # gating on the class.  A hand-built object with a ``basis`` attribute
    # is judged identically to a DreamingClaim.
    census = WorldCensus(n_financial=1, n_bootstrap=60)
    assert claim_basis(_BareClaim(TOTAL_BASIS)) == TOTAL_BASIS
    assert rejects_dreaming_claim(_BareClaim(TOTAL_BASIS), census) is True


@pytest.mark.parametrize("basis", ["financial", "total"])
def test_claim_basis_reads_the_two_spellings(basis: str) -> None:
    assert claim_basis(DreamingClaim(basis)) == basis


@pytest.mark.parametrize("bad", ["nope", "", None, "Financial", 7])
def test_a_claim_that_names_no_usable_basis_is_refused(bad: object) -> None:
    # A claim must say whether it rests on the financial figure the gate
    # reads or on the bootstrap-padded total the ladder reads; a claim that
    # names neither — or a misspelling of one — is resting on a pool this
    # module cannot judge, and is refused before the census is consulted.
    with pytest.raises(BootstrapPoolError, match="rests on a pool"):
        claim_basis(DreamingClaim(bad))  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", ["nope", "", None, 7])
def test_a_bare_claim_with_a_bad_basis_is_refused(bad: object) -> None:
    # The concrete claim validates its basis at its making, so a claim that
    # cannot be judged is refused where it is made rather than where it is
    # judged.
    with pytest.raises(BootstrapPoolError, match="rests on a pool"):
        DreamingClaim(bad)  # type: ignore[arg-type]


def test_the_refusal_is_consulted_only_for_a_usable_claim() -> None:
    # A malformed claim answers no verdict: the basis is checked first, so
    # a claim that names no usable basis never reaches the census.  Proven
    # by handing a census that would otherwise be admitted and a claim that
    # cannot be judged — the refusal is the basis, not the figures.
    census = WorldCensus(n_financial=M3_GATE_WORLDS, n_bootstrap=0)
    with pytest.raises(BootstrapPoolError):
        rejects_dreaming_claim(_BareClaim("nope"), census)


# -- The census is the seam, and the two figures are held apart ---------------------


def test_the_judgment_reads_the_census_two_figures_apart() -> None:
    # The refusal is the exact inversion of §10.6's rule: a report that let
    # a total claim through on a thin financial figure would be reading a
    # gain on hyperparameter search as a gain on alpha discovery.  Pinned
    # on the same census in both bases, so the two figures — not the basis
    # a claim happens to name — are what the judgment turns on.
    census = WorldCensus(n_financial=1, n_bootstrap=60)
    assert rejects_dreaming_claim(DreamingClaim(TOTAL_BASIS), census) is True
    assert rejects_dreaming_claim(DreamingClaim(FINANCIAL_BASIS), census) is False


def test_a_dreaming_claim_is_a_frozen_statement_of_its_basis() -> None:
    # A claim is a statement rather than a state: two callers holding one
    # hold the same basis, and the judgment it earns cannot be moved by
    # editing it in place.
    claim = DreamingClaim(TOTAL_BASIS)
    assert DreamingClaim(TOTAL_BASIS) == claim
    with pytest.raises(dataclasses.FrozenInstanceError):
        claim.basis = FINANCIAL_BASIS  # type: ignore[misc]


def test_the_refusal_vocabulary_is_the_pools() -> None:
    # Every way this judgment can fail is a fact about the pool's reporting
    # contract, so every refusal raises BootstrapPoolError — the same
    # vocabulary the census speaks — and a caller that catches a census
    # refusal catches this one too.
    census = WorldCensus(n_financial=1, n_bootstrap=60)
    with pytest.raises(BootstrapPoolError):
        claim_basis(_BareClaim("nope"))
    with pytest.raises(BootstrapPoolError):
        rejects_dreaming_claim(DreamingClaim(TOTAL_BASIS), census, gate=True)  # type: ignore[arg-type]
