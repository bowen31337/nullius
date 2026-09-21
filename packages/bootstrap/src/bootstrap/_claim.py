"""The headline refusal — feature 187's judgment about a dreaming claim.

app_spec.xml, "Bootstrap Worlds", feature 187: *System rejects a headline
dreaming claim resting on bootstrap worlds alone, because bootstrap and
financial pools report separately.*  docs/nullius-tech-architecture.md
§10.6 states the rule the sentence exists to enforce, and states it as a
reporting rule before it states it as a counting rule:

    **Report the two pools separately.**  A gain that only appears on
    bootstrap worlds is a gain on hyperparameter search, not on alpha
    discovery.  The orchestrator tracks ``n_financial`` independently and
    the M3 gate is evaluated on financial holdout worlds only.

§10.6.1 restates the same rule for the ported half, in the one sentence
that makes the counting direction asymmetric — bootstrap worlds may raise
``n`` but must never raise ``n_financial``:

    ... it pads ``n``, never ``n_financial``.  The M3 gate is still
    evaluated on financial holdout worlds only.

**Why this module is a judgment about a claim, and not a third count.**
Feature 186 (:mod:`bootstrap._census`) already returns the two figures a
report is made of — ``n_financial`` and ``n_bootstrap``, held separately so
neither can be derived from the other — and it deliberately renders no
verdict, because a verdict is not a count.  This module is the verdict the
census declines to make: it takes a :class:`~bootstrap.WorldCensus` (both
figures, held apart) and a *claim* that dreaming should proceed, and it
decides whether the claim is one the financial evidence alone supports or
one that is propped up by the bootstrap half.  That is the shape the
feature's sentence names — *"rejects a headline dreaming claim resting on
bootstrap worlds alone"* — and it is a shape that cannot live in the
census: the census knows the two numbers but not the claim, and a counting
module that decided what a claim may be claimed to support would be
answering a question about a report from inside a count.  So the census
reports and this module judges, and the two figures are the seam between
them.

**What "resting on bootstrap worlds alone" means, and why it is a gate, not
a threshold.**  The M3 gate is evaluated on financial holdout worlds only,
and §10.3.1 derives its ``n > 53`` precondition from the paired comparison's
power — a number of *financial* worlds, because the paired ΔIR test is run
on financial holdout worlds, not on hyperparameter-search ones.  A dreaming
claim is therefore admissible only when the financial figure the gate reads
is itself at or above the gate: when ``n_financial`` clears it, the claim
stands on the evidence the gate was meant to see, and the bootstrap pool is
irrelevant to the decision.  The claim *rests on bootstrap worlds alone*
when the financial figure falls short of the gate yet the claim would
proceed anyway — that is, when it can only get to "go" by counting the
bootstrap half.  The refusal is the exact inversion of §10.6's rule: a
report that let the claim through there would be reading a gain on Lasso
solving as a gain on alpha discovery, which is the one failure both §10.6
and §10.6.1 name.

**The bootstrap-padded total is the sharper form of the same failure, and
it is refused too.**  A claim that does not name a figure at all but merely
asserts "we have enough worlds to dream" is the common case, and the number
such a claim reaches for is the *total* — §12.1's ladder reading,
``n_financial + n_bootstrap`` — because the ladder is the precondition a
dreaming cycle reads before it runs ("below 20 worlds", "between 20 and
50").  Admitting a claim on the total when the financial figure is short is
the same inversion, spelled one level up: it lets 45 generated
hyperparameter-search worlds stand in for 45 crypto campaigns at the M3
gate.  So a bare claim is judged against the financial figure alone, and a
claim that reaches for the total is refused whenever the bootstrap half is
what carries it over the gate.  The census's :attr:`~bootstrap.
WorldCensus.total` — the one thing it ships that mixes the two pools — is
therefore exactly the number this module must not let a claim lean on, and
the refusal names it so an operator reading the failure can see which pool
the claim was really resting on.

**The gate is a parameter, and it is not hard-wired to §10.3.1's 53.**  The
precondition a financial dreaming claim must meet is the M3 gate's own
world count, which §10.3.1 derives (``n > 53`` at the committed ``M`` and
``σ_V``) but which a deployment may set differently.  The gate is therefore
a keyword of the refusal, defaulting to the §10.3.1 figure the feature was
written against, validated to be a non-negative whole number so a gate that
is not a world count cannot silently admit or block a cycle.  A claim is
admissible when ``n_financial`` meets the gate; it is refused when it does
not and the claim would proceed on the bootstrap-padded reading.  The gate
is a *floor* the financial evidence must reach, not a band — there is no
upper edge, because §10.3.1's precondition is a power floor and more
financial worlds only strengthen the comparison.

**What a claim is, and why it is duck-typed.**  A claim is the thing a
dreaming cycle or an operator script asserts when it asks to proceed: at
minimum whether it is leaning on the financial figure alone or on the
bootstrap-padded total.  It is duck-typed rather than ``isinstance``-gated
for the reason feature 184's question, feature 189's labeling and feature
186's census all are — the module loader hands out a second copy of every
class under a synthetic name, and an ``isinstance`` gate would refuse the
very object composition serves.  What is checked is the surface the
judgment reads: the claim's ``basis`` — ``"financial"`` when it rests on
the gate figure, ``"total"`` when it rests on the ladder's sum — and a
claim that names no basis, or names one this module cannot speak, is
refused naming what was missing, before the census is consulted.

**The refusal vocabulary is the pool's, and that is the seam.**  Every way
this judgment can fail is a fact about the *pool's* reporting contract
rather than about a world or a label: the claim rests on bootstrap worlds,
the claim names no usable basis, the object handed in is not a census.
None of those is a world that cannot be named (:class:`~bootstrap.
BootstrapWorldError`) or an arithmetic that had no answer (:class:`~
bootstrap.BootstrapScoringError`), so every refusal raises :class:`~
bootstrap.BootstrapPoolError` — "the ask was never about a world" — the
same vocabulary the census speaks, so a caller that catches a census
refusal catches this one too and a fourth class would be a distinction the
caller's ``except`` cannot act on.  The census itself is validated by
relying on its own construction-time guards (a hand-built census with an
impossible figure refuses itself), so this module does not re-check the two
figures: it was handed a census, and the census is the seam.

**What this module deliberately does not ship.**  It counts nothing (the
two figures are the census's reads, made where both are visible), persists
nothing (the refusal is a judgment, not evidence — §9.1's ledger is the
trial's to write), charges no budget (feature 185's ``charges_budget`` is
the trial's fact), and renders no other verdict than the one the sentence
names.  It does not decide whether a claim that *does* rest on financial
worlds is true — only whether it rests on the right pool — because the
feature is a reporting discipline, not a truth test: a claim resting on
financial worlds may still be wrong, and that is the scorer's to find.  It
adds no component and no app seat: the judgment is a read over the census a
component builder already exposes and the claim a caller brings, so it is a
free function beside them, the way :func:`~bootstrap.ground_truth` and
:func:`~bootstrap.world_census` are — registering a component for it would
put a name in the registry for a question that resolves no configuration of
its own.

Stdlib only, and import-cheap: no ``sqlite3``, no third-party import at
module scope, so the factory's scan — which imports this package to fire
its ``@register`` — pays nothing for the refusal.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ._census import WorldCensus
from .errors import BootstrapPoolError

__all__ = [
    "FINANCIAL_BASIS",
    "M3_GATE_WORLDS",
    "TOTAL_BASIS",
    "DreamingClaim",
    "claim_basis",
    "rejects_dreaming_claim",
]

#: The basis of a claim that rests on the gate's own figure — the financial
#: world count.  A claim on this basis is admissible when ``n_financial``
#: meets the gate, because the gate is evaluated on financial holdout
#: worlds only and the bootstrap half is irrelevant to it.
FINANCIAL_BASIS = "financial"

#: The basis of a claim that rests on the ladder's sum — ``n_financial +
#: n_bootstrap``.  A claim on this basis rests on bootstrap worlds when the
#: bootstrap half is what carries it over the gate, which is the failure
#: §10.6 and §10.6.1 both name, so it is refused there.
TOTAL_BASIS = "total"

#: The world count the M3 gate's paired comparison needs — §10.3.1's
#: ``n > 53`` at the committed ``M`` and ``σ_V``, the floor a financial
#: dreaming claim must meet.  The default the refusal judges against; a
#: deployment that sets its own gate passes it as the ``gate`` keyword.
M3_GATE_WORLDS = 53


@dataclass(frozen=True)
class DreamingClaim:
    """A claim that dreaming should proceed — the judgment's subject.

    The concrete shape of a dreaming claim: the basis it rests on —
    :data:`FINANCIAL_BASIS` when it rests on the gate's own financial world
    count, :data:`TOTAL_BASIS` when it rests on the ladder's bootstrap-
    padded sum.  Frozen, because a claim is a *statement* rather than a
    state: two callers holding one claim hold the same basis, and the
    judgment it earns cannot be moved by editing it in place.

    Built by a caller that wants a named claim rather than any object with
    a ``basis`` attribute — the dreaming cycle that asserts "we have enough
    worlds to dream" hands over one of these, and :func:`rejects_dreaming_
    claim` reads its ``basis`` duck-typed, so a hand-built object with the
    same attribute is judged identically.  The basis is validated at
    construction, so a claim that names a basis this module cannot speak is
    refused where it is made rather than where it is judged.
    """

    basis: str

    def __post_init__(self) -> None:
        # The same two spellings claim_basis speaks, checked once here so a
        # claim that cannot be judged is refused at its making.
        if self.basis not in (FINANCIAL_BASIS, TOTAL_BASIS):
            raise BootstrapPoolError(
                f"a dreaming claim rests on a pool — its basis must be "
                f"{FINANCIAL_BASIS!r} (the financial world count the M3 "
                "gate reads) or "
                f"{TOTAL_BASIS!r} (the bootstrap-padded total the ladder "
                f"reads), got {self.basis!r}; a claim that names neither "
                "is resting on a pool this module cannot judge"
            )


def claim_basis(claim: Any) -> str:
    """The basis a dreaming claim rests on — ``"financial"`` or ``"total"``.

    Duck-typed rather than ``isinstance``-gated, for the reason feature
    184's question and feature 186's census are: the module loader hands
    out a second copy of every class under a synthetic name, so a gate on
    the class object would refuse the very claim composition serves.  What
    is read is the surface the judgment needs — the claim's ``basis`` — and
    a claim that carries no usable basis, or one this module cannot speak,
    is refused naming what was missing, before the census is consulted.

    The two spellings are the only ones this module speaks, and they are
    the two pools the census holds apart: a claim that rests on the gate
    figure (:data:`FINANCIAL_BASIS`) is judged on ``n_financial`` alone,
    and a claim that rests on the ladder's sum (:data:`TOTAL_BASIS`) is
    judged on whether the bootstrap half is what carries it over the gate.
    """
    basis = getattr(claim, "basis", None)
    if basis not in (FINANCIAL_BASIS, TOTAL_BASIS):
        raise BootstrapPoolError(
            f"a dreaming claim rests on a pool — got {claim!r} "
            f"({type(claim).__name__}), whose basis is {basis!r}; a claim "
            "must say whether it rests on the financial world count the M3 "
            f"gate reads ({FINANCIAL_BASIS!r}) or on the bootstrap-padded "
            f"total the ladder reads ({TOTAL_BASIS!r}), and a claim that "
            "names neither is resting on a pool this module cannot judge"
        )
    return basis


def _validated_gate(gate: Any) -> int:
    """Check that ``gate`` is a world count, or refuse it.

    The one spelling of what the gate must be, shared by
    :func:`rejects_dreaming_claim`.  A gate is the M3 precondition's world
    count — §10.3.1's ``n > 53`` — so it is a non-negative whole number,
    and a value that is not one would silently admit or block a dreaming
    cycle on a number that is not a world count.  A ``bool`` is refused
    where a count belongs for the reason the census refuses one on a
    figure: ``True`` is ``1`` in Python, so a flag where a gate belongs
    would name the thinnest admissible pool.
    """
    if isinstance(gate, bool) or not isinstance(gate, int):
        raise BootstrapPoolError(
            f"the M3 gate is a world count — got {gate!r} "
            f"({type(gate).__name__}); §10.3.1's paired comparison needs a "
            "number of financial holdout worlds, and a value that is not a "
            "whole number names no gate a dreaming cycle can be judged "
            "against"
        )
    if gate < 0:
        raise BootstrapPoolError(
            f"the M3 gate is a non-negative world count — got {gate!r}; a "
            "paired comparison needs zero worlds or more, and a negative "
            "gate would admit every dreaming cycle, which is the gate "
            "§10.6 exists to keep shut"
        )
    return gate


def _rests_on_bootstrap(census: WorldCensus, basis: str, gate: int) -> bool:
    """Whether the claim, on its basis, clears the gate only on the bootstrap half.

    A claim rests on bootstrap worlds alone when the financial figure the
    gate reads falls short of the gate, yet the claim's *own* basis figure
    clears it — that is, when the bootstrap half is what carries the claim
    over the gate.  The two bases read the gate differently, and the split
    is the whole point:

    * A :data:`FINANCIAL_BASIS` claim's figure *is* ``n_financial`` — the
      gate's own count.  Once ``n_financial`` is found short of the gate,
      such a claim clears on nothing: it fails on financial grounds, which
      is the gate's to decide, not this judgment's.  It never leans on the
      bootstrap half, so it is never refused here — a thin financial claim
      is rejected by the gate for being thin, not by this feature for
      resting on the wrong pool.
    * A :data:`TOTAL_BASIS` claim's figure is the ladder's sum,
      ``n_financial + n_bootstrap``.  When ``n_financial`` is short but the
      total clears the gate, the claim gets to "go" only because the
      bootstrap half pads the sum — that is the precise inversion §10.6 and
      §10.6.1 name, and it is refused.  When the total is short too, the
      claim fails on the gate regardless of which pool it counts, so it is
      not resting on bootstrap worlds — it is merely thin — and it is left
      to the gate.

    So the refusal is exactly ``n_financial < gate`` **and** the claim
    names the total **and** the total clears the gate.  A claim whose
    financial figure already meets the gate stands on the pool the gate was
    meant to see whatever basis it names — the bootstrap half cannot be
    what carries it over — so it is admitted.
    """
    if census.n_financial >= gate:
        return False
    return basis == TOTAL_BASIS and census.total >= gate


def rejects_dreaming_claim(
    claim: Any,
    census: WorldCensus,
    *,
    gate: int = M3_GATE_WORLDS,
) -> bool:
    """Whether a headline dreaming claim rests on bootstrap worlds alone.

    The one judgment for feature 187's sentence, the way :func:`~bootstrap.
    world_census` is the one factory for the census and :func:`~bootstrap.
    ground_truth` the one factory for the labeling: a dreaming claim and a
    census in, a verdict out.  It decides whether the claim is one the
    financial evidence alone supports or one that is propped up by the
    bootstrap half — *"rejects a headline dreaming claim resting on
    bootstrap worlds alone, because bootstrap and financial pools report
    separately"*.

    The claim is duck-typed on its :func:`claim_basis` (``"financial"`` or
    ``"total"``); the census is the seam — its two figures, held apart, are
    the whole of what the judgment reads; and ``gate`` is the M3 world
    count the financial figure must meet, §10.3.1's ``n > 53`` by default.
    A claim is refused as resting on bootstrap worlds — this function
    answers ``True`` — when the financial figure falls short of the gate and
    the claim would nonetheless proceed, either because it names the total
    as its basis or because the bootstrap-padded total is what carries it
    over the gate.  When ``n_financial`` meets the gate, the claim stands on
    the pool the gate was meant to see and this function answers ``False``.

    Refuses, in this order, each naming what it is about:

    1. a claim that names no usable basis — refused before the census is
       consulted, so a malformed claim answers no verdict;
    2. a ``gate`` that is not a non-negative whole number — a gate that is
       not a world count cannot judge a dreaming cycle.

    Renders no verdict on a claim that rests on financial worlds beyond the
    pool it rests on: such a claim may still be wrong, and that is the
    scorer's to find.  This function decides only which pool the claim
    leans on, which is the reporting discipline §10.6 and §10.6.1 state and
    the whole of the feature's sentence.
    """
    basis = claim_basis(claim)
    gate = _validated_gate(gate)
    return _rests_on_bootstrap(census, basis, gate)
