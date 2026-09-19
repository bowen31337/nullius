"""Embargoing the lookback length after every split boundary — pipeline step 6.

app_spec.xml feature 78: *"System embargoes the lookback length after every
split boundary, which rejects a fold configuration whose embargo is 0
periods."* docs/nullius-tech-architecture.md §6.1 names the step — ``6.
purge_and_embargo  purge H, embargo L around every CV split`` — and §C2 of
the PRD states the rule: *"Apply purged k-fold with embargo — purge ``H``
(holding period), embargo ``L`` (lookback) around every split."*

**The leak the embargo closes — the purge's mirror image.** The purge
(feature 77) stops a training bar's *label* reaching across the split: a
label is a forward return, so a training bar inside the holding period of
the split trains on a test-set price. The embargo stops the same crossing
in the other direction, through the *features*. Every bar the pipeline
scores — training bars included — is scored from a window of the trailing
``L`` bars (step 1: ``materialize_window(snapshot, t, lookback=L,
universe=U)``), so a training bar that sits within ``L`` bars *after* a
split boundary is scored from features built out of test-half bars. The
model does not read the test set through its labels; it reads it through
its inputs. The embargo keeps the ``L`` bars after every split boundary out
of training, which is why the feature sentence fixes its length to the
lookback: an embargo shorter than the lookback leaves test bars inside the
windows of the first training bars that follow the boundary, and an
embargo longer than it is caution on top, not a leak.

**Why this module certifies a configuration, not dates.** Within the
one-split fold the purge check certifies, the embargo's date-side has
nothing to bite on: that fold puts the whole training half strictly before
the split (the purge refuses a training bar past it), so no training bar
of *this* fold sits after any boundary. The bars the embargo removes are
removed when the folds are *drawn* — the cross-validation driver keeps
training out of the embargo periods after every test half, in whatever
fold's training data follows it. What this step can and must certify is
the promise that driver runs under: the fold configuration's
``embargo`` — the count of periods training is kept out after every
boundary. The rule is the feature's first clause: that count must be the
lookback length or more. And that is why the refusal half lands on a
configuration — a fold configuration whose embargo is 0 periods is a
driver that will resume training on the very bar after every split, whose
first training bars are windows full of test-half bars. Rejected, with the
refusal naming how many periods the embargo falls short.

**The rule, stated once.** With the fold configuration's embargo ``E``
(grid periods) and the lookback ``L`` (grid bars, the trailing span the
signal's windows are built from), the configuration is embargoed exactly
when::

    E ≥ L

A period is one bar on the market grid — the same ruler feature 77
measures the holding period against, not a calendar day. The
**shortfall** the verdict reports is how many periods the embargo falls
short of the lookback — the number of further periods that must be
embargoed after every split boundary (or bars taken off the lookback)
before the configuration is one the pipeline can run. On a verdict this
module returns it is always ``0``; a configuration that falls short is
raised, not returned.

**What this module does not do.** It does not split (a caller draws the
folds), it does not drop the bars (a caller keeps the embargo periods
after every boundary out of the training halves it draws), it does not
purge (feature 77 — the same step's other half, checked against dates
because that is where its leak shows), it does not align targets (feature
75) or apply costs (feature 79). It takes the fold configuration's
embargo and the lookback the signal's windows are built from, and answers
exactly the one question the feature's first clause puts in scope: *does
this configuration embargo the lookback length after every split
boundary?* — raising when it does not, so a configuration that would march
training up to every split boundary never draws the folds it would leak
through.

**The layering note.** This module is stdlib-only — two bar counts and a
plain record, no polars, no pyarrow, no lake, no environment, no
numerics. It is the cheapest import in this package alongside the purge it
pairs with, because an embargo check is a statement about a count, not a
computation over a frame. Importing this member therefore costs
composition — and the replay path §1 forbids from reaching the evaluator —
nothing at all, matching the import-cheap discipline the rest of this
package holds to.
"""

from __future__ import annotations

from dataclasses import dataclass

from ._errors import EvaluatorEmbargoError

__all__ = [
    "EmbargoCheck",
    "check_fold_embargoed",
]


@dataclass(frozen=True)
class EmbargoCheck:
    """The verdict of a fold configuration's embargo check.

    The value feature 78's step returns when a configuration *is*
    embargoed: the embargo, the lookback it must cover, and the shortfall —
    always ``0`` here, because :func:`check_fold_embargoed` raises for a
    configuration that falls short rather than returning one. Carried
    beside the configuration it describes, filed in a report, or compared
    across configurations without recomputing (frozen, hashable).
    """

    #: The fold configuration's embargo, in grid periods — the count of
    #: bars training is kept out after every split boundary.
    embargo: int
    #: The lookback the signal's windows are built from, in grid bars —
    #: the length that must be embargoed, because a training bar within it
    #: of a boundary is scored from features built out of test-half bars.
    lookback: int
    #: How many grid periods the embargo falls short of the lookback — the
    #: number of further periods to embargo after every split boundary (or
    #: bars to take off the lookback) before the configuration can run.
    #: Always ``0`` on a record this module returns (a short embargo is
    #: raised, not returned); carried so a hand-built verdict can name a
    #: configuration a caller is inspecting.
    shortfall: int

    def __post_init__(self) -> None:
        # Read-only validation of the values the constructor accepted; the
        # dataclass is frozen, so nothing here writes back.
        for name in ("embargo", "lookback", "shortfall"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise EvaluatorEmbargoError(
                    f"{name} must be an integer count of grid bars, got "
                    f"{value!r} ({type(value).__name__})"
                )
        for name in ("embargo", "lookback"):
            if getattr(self, name) <= 0:
                raise EvaluatorEmbargoError(
                    f"{name} must be at least one grid bar, got "
                    f"{getattr(self, name)}"
                )
        if self.shortfall < 0:
            raise EvaluatorEmbargoError("shortfall cannot be negative")
        # The three fields cohere: a record claiming a shortfall of zero
        # while its embargo falls short — or claiming a shortfall it does
        # not have — is a verdict misdescribing the configuration it
        # carries, and unlike the purge's shortfall (a distance on a grid
        # the record does not hold), this one is closed-form in fields the
        # record does.
        expected = max(0, self.lookback - self.embargo)
        if self.shortfall != expected:
            raise EvaluatorEmbargoError(
                f"shortfall is {self.shortfall}, but the embargo "
                f"{self.embargo} falls {expected} "
                f"{'period' if expected == 1 else 'periods'} short of the "
                f"lookback {self.lookback}; a verdict must describe the "
                "configuration it carries"
            )

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"EmbargoCheck(embargo={self.embargo}, "
            f"lookback={self.lookback}, shortfall={self.shortfall})"
        )


def check_fold_embargoed(embargo: object, lookback: object) -> EmbargoCheck:
    """Certify that a fold configuration embargoes the lookback length.

    Pipeline step 6 (§6.1), the embargo half: a cross-validation fold's
    training is kept out of the ``embargo`` periods after every split
    boundary, because every bar the pipeline scores is scored from a window
    of the trailing ``lookback`` bars, and a training bar within that span
    of a boundary is scored from features built out of test-half bars.
    This function certifies that the configuration's embargo covers the
    lookback, and **raises** when it does not — an un-embargoed
    configuration is refused, never returned, so it can never draw the
    folds it would leak through.

    ``embargo`` is the fold configuration's embargo, in grid periods — the
    count of bars training is kept out after every split boundary, one
    spelling of which is the resolved configuration's
    ``embargo_periods``. ``lookback`` is the lookback the signal's windows
    are built from, in grid bars — step 1's
    ``materialize_window(snapshot, t, lookback=L, ...)`` — the length the
    feature's first clause embargoes after every boundary.

    The configuration is embargoed exactly when ``embargo ≥ lookback``; an
    embargo wider than the lookback passes, because caution on top of the
    leak line is not a leak.

    Returns an :class:`EmbargoCheck` naming the embargo, the lookback and
    the shortfall (``0``). Raises :class:`EvaluatorEmbargoError`, each with
    its reason (see ``_errors``): an ``embargo`` that is not a positive
    integer count of periods — ``0`` named explicitly, because a fold
    configuration whose embargo is 0 periods is the feature's own refusal;
    a ``lookback`` that is not a positive integer count of bars; and an
    embargo that falls short of the lookback — the configuration is
    un-embargoed, and the refusal names how many periods it falls short.
    """
    if isinstance(embargo, bool) or not isinstance(embargo, int):
        raise EvaluatorEmbargoError(
            "embargo must be a positive integer number of grid periods — "
            "the count training is kept out after every split boundary — "
            f"got {embargo!r} ({type(embargo).__name__})"
        )
    if embargo <= 0:
        raise EvaluatorEmbargoError(
            f"embargo must be at least one grid period, got {embargo}; a "
            "fold configuration whose embargo is 0 periods resumes training "
            "on the bar after every split boundary, and that bar's window is "
            "built from test-half bars — the embargo must cover the lookback"
        )
    if isinstance(lookback, bool) or not isinstance(lookback, int):
        raise EvaluatorEmbargoError(
            "lookback must be a positive integer number of grid bars — the "
            "trailing span the signal's windows are built from — got "
            f"{lookback!r} ({type(lookback).__name__})"
        )
    if lookback <= 0:
        raise EvaluatorEmbargoError(
            f"lookback must be at least one grid bar, got {lookback}; a "
            "lookback of zero bars is a window with nothing in it — there "
            "would be no features for the embargo to keep test-half bars "
            "out of, and no signal to evaluate"
        )

    # The leak line is the lookback itself: the first training bar after
    # the embargo reaches ``lookback`` bars back, so an embargo short of it
    # leaves test-half bars inside that bar's window. The shortfall is how
    # many more periods of embargo reach the line — the number to widen the
    # embargo by (or bars to take off the lookback) before the fold
    # configuration can draw folds.
    shortfall = lookback - embargo
    if shortfall > 0:
        raise EvaluatorEmbargoError(
            "the fold configuration's embargo does not cover the lookback: "
            f"the embargo is {embargo} periods after every split boundary "
            f"and the lookback is {lookback} bars, so the embargo falls "
            f"{shortfall} {'period' if shortfall == 1 else 'periods'} short "
            "— the first training bar after the embargo is scored from a "
            "window that reaches across the boundary into the test half — "
            "raise the embargo to the lookback length, or shorten the "
            "lookback, and re-check"
        )

    return EmbargoCheck(embargo=embargo, lookback=lookback, shortfall=0)
