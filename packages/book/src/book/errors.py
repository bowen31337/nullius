"""The book member's refusal vocabulary — features 301, 303, 304, 305, 306, 307
and 308.

app_spec.xml, "Portfolio Book Construction", feature 301: *System combines
promoted signals by information-ratio weighting, which returns a single
composite target score per symbol.*  A combine can fail only because the
promoted signals it was handed cannot be weighted into a book, and this
module is the one place those failures are named.

app_spec.xml, feature 308 — this category's second sentence — is the sibling:
*System rejects a leverage target above one quarter of the Kelly fraction
implied by the book Sharpe and volatility.*  Its refusals live here beside
301's, for the reason 301's own docstring states this module exists at all:
one base class, so a caller can refuse the whole book surface with a single
``except``.  The two sentences' failures are different facts about different
figures — a *signal* that cannot be weighted (301) and a *leverage target*
the resulting book may not carry (308) — so the cap's classes are **named
siblings under :class:`BookConstructionError`** rather than additions to it:
a caller that must react differently to *your signals cannot be combined* and
*this book may not carry that leverage* distinguishes them by class, while a
caller that refuses book work wholesale goes on catching the one base — the
one-base-per-member shape the dreaming and regime members state for their own
vocabularies.

app_spec.xml, feature 306 — the category's boundary sentence — is the third
face: *System keeps book construction human-authored and version-controlled,
which rejects any agent-authored modification to it.*  Its refusals join the
other two here for the same reason they did: the base stays one, and the
sentence's two failures are different facts about a different subject — a
*change record* that cannot be stated (306's ask) and a *change* that was
authored by an agent (306's judgment), where 301's subject was a signal and
308's a leverage target.  The guard's classes are siblings under the base
exactly as the cap's are, and for the same reason: a caller that must react
differently to *an agent authored this change to the construction* and *your
change could not be stated* distinguishes them by class, while a caller that
refuses book work wholesale still writes one ``except``.

One base class, :class:`BookConstructionError`, so a caller — the order
layer, a seat, a test — can refuse the whole refusal surface with a single
``except``.  Every message opens with a greppable one-word code (the
``pool_frozen`` / ``unwalkable_tree`` precedent), so an operator greps one
word for the refusal; and every message names the signal (by ``signal_id``)
and, where a symbol is at issue, the symbol, so the refusal is actionable
without a stack trace.

The codes are the vocabulary of the act, and each names *what the caller
must do about it*:

* ``empty_book`` — no signals were handed, so there is nothing to weight;
* ``unnamed_signal`` — a signal carries no ``signal_id`` to attribute a
  weight to;
* ``duplicate_signal`` — two signals share a ``signal_id``;
* ``non_positive_ir`` — a signal's information ratio is zero or negative,
  so its standing to weight the book is undefined (refused, not
  zero-weighted, because silently dropping a losing signal would hide a
  portfolio decision);
* ``non_finite_ir`` — a signal's information ratio is NaN or ±inf;
* ``signal_without_scores`` — a signal carries no target scores;
* ``non_finite_score`` — a signal's score for a symbol is NaN or ±inf;
* ``uncovered_symbol`` — a signal carries no score for a symbol the book
  covers (refused, not zero-filled — absence is not a view).

The combiner raises these before it forms any composite, so a refused
combine leaves no value behind.

The leverage cap adds one code, and it is the only one an operator greps a
deployment log for on feature 308's path:

* ``leverage_above_quarter_kelly`` — the leverage target a caller means to
  hold sits above one quarter of the book's Kelly fraction: a long position
  on a book whose edge does not fund it (refused rather than scaled down,
  because lowering a target the caller asked for would be this member
  *sizing* a position, and sizing is the order layer's act rather than a
  bound's).

app_spec.xml, feature 303 — this category's second act — is a further face:
*System applies volatility targeting to the combined book, which returns
weights scaled to a configured annualized volatility.*  Its refusals join the
others here for the reason the cap's did: the base stays one, and the
sentence's two failures are different facts about a different subject — the
*combined book* that cannot be normalized into a book at all (303's judgment)
and the *figures* the act is asked for (303's ask), where 301's subject was a
signal and 308's a leverage target.  The act adds the third code an operator
greps a deployment log for:

* ``flat_book`` — the combined book's composite target scores are all zero, so
  its gross score is exactly nothing and the normalization the act's first
  step performs is a division by nothing: there is no book of weights to
  scale, and answering an all-zero weight set would counterfeit a book from no
  view (refused rather than zero-filled, the stance feature 301 takes on a
  signal that misses a symbol, read on this act's own divisor).

The act's two faces are the same pair of shapes the cap's and the guard's are —
the ask's own facts (:class:`VolatilityTargetRequestError`, no code, because a
malformed ask names its subject in its first words) and the one judgment the
sentence mints (:class:`VolatilityTargetError`, carrying the code above).  Both
are subclasses of the base with the same consequence, and the same reason to be
siblings rather than aliases: a flat composite is refusable though both figures
were perfectly well stated, and a mis-stated figure is refusable though the
book expresses a perfectly good view, so the two facts are genuinely different.

app_spec.xml, feature 304 — §C8's next link, *"position and concentration
limits"* — is a further face: *System applies per-position and concentration
limits, which rejects a target weight breaching either bound.*  Its refusals
join the others here for the reason the act's did: the base stays one, and the
sentence's two failures are different facts about a different subject — the
*target weights* that sit outside the deployment's bounds (304's judgment) and
the *figures* the act is asked for (304's ask), where 303's subject was the
book being normalized and 308's a leverage target.  The act adds the fourth and
fifth codes an operator greps a deployment log for:

* ``position_above_limit`` — a target weight's magnitude is above the
  per-position limit: one position is larger than the deployment configured it
  may be (refused rather than scaled down, because lowering a target the caller
  asked for would be this member *sizing* a position, and sizing is the order
  layer's act rather than a bound's);
* ``concentration_above_limit`` — the book's largest position is a larger share
  of its gross exposure than the concentration limit admits: the book's *shape*
  is outside the bound (refused rather than re-weighted, because re-weighting
  would be answering a question about feature 301's combiner from inside a
  bound).

Two codes rather than one shared token, for the reason the router's limiter
carries two: the repairs differ — *shrink that position* against *spread the
book* — and a reader greps the word for the one they have to fix.

The act's two faces are the same pair of shapes the others are — the ask's own
facts (:class:`LimitRequestError`, no code, because a malformed ask names its
subject in its first words) and the one judgment the sentence mints
(:class:`LimitBreachError`, carrying whichever of the two codes the breached
bound names).  Both are subclasses of the base with the same consequence, and
the same reason to be siblings rather than aliases: a breaching book is
refusable though both limits were perfectly well stated, and a mis-stated limit
is refusable though the book sits inside a perfectly good bound, so the two
facts are genuinely different.

app_spec.xml, feature 305 — the last arrow of §C8's own chain — is a further
face: *System returns final target weights as the only output consumed by the
order layer.*  Its refusals join the others here for the reason the limits' did:
the base stays one, and the sentence's two failures are different facts about a
different subject — the value that is not a published book at all (305's ask)
and an instruction carrying a second published set beside the one meant for the
orders (305's judgment), where 304's subject was target weights outside the
deployment's bounds.  The act adds the two codes an operator greps a deployment
log for on this path:

* ``no_book`` — what the caller handed over is not a book: a value carrying no
  ``weights``, a non-mapping, a published set covering no symbols, or a value
  meant for the order layer that declares itself nothing (refused rather than
  passed on as an instruction, because an instruction naming no book is the
  *absence* of a book — a book held flat is every symbol weighted ``0.0``, and
  that one is published);
* ``annexed_record`` — a second record declaring itself the order layer's output
  is in the instruction (refused rather than reconciled, because two published
  sets leave the order layer choosing between them, which is the construction's
  own act performed one layer down with no bound re-run).

The act's two faces are the same pair of shapes the others are — the ask's own
facts (:class:`FinalWeightsRequestError`, carrying ``no_book`` where the value
is not a book and no code where a book was well stated but badly stated key by
key) and the one judgment the sentence mints
(:class:`OrderLayerOutputError`, carrying ``annexed_record``).  Both are
subclasses of the base with the same consequence, and the same reason to be
siblings rather than aliases: an instruction carrying a second published set is
refusable though both sets are perfectly well stated, and a value carrying no
book is refusable though no second record is involved, so the two facts are
genuinely different.

The authorship guard adds the second, and it is the one an operator greps
a deployment log for on feature 306's path — the refusal that says the
search reached for the construction:

* ``agent_authored_modification`` — the change handed to the guard was
  authored by an agent: an automated author — the discovery loop, the
  dreaming reviser, a worker, the system's own cast of authors — proposed
  a modification to the book construction, and the construction is the one
  thing docs/alpha-engine-prd.md §C8 holds *"explicitly outside the search
  space"* (refused rather than relabelled, because an author vocabulary the
  module could be talked out of would be the whole guard).

The guard's two faces are the same pair of shapes the cap's are — the
ask's own facts (:class:`BookChangeRequestError`, no code, because a
malformed change names its subject in its first words) and the one
judgment the sentence mints
(:class:`AgentAuthoredModificationError`, carrying the code above).  Both
are subclasses of the base with the same consequence, and the same reason
to be siblings rather than aliases: an agent-authored change is refusable
though perfectly well stated, and a mis-stated change is refusable though
a human authored it, so the two facts are genuinely different.

The cap's two faces are the pair of classes below — the ask's own facts
(:class:`LeverageRequestError`, no code, because a malformed ask names its
subject in its first words) and the one judgment the sentence mints
(:class:`LeverageTargetError`, carrying the code above).  Both are subclasses
of the base, so the caller that refuses the whole book surface still writes
one ``except``; and because they are *siblings of* rather than *aliases for*
:class:`BookConstructionError`, the caller that has to react differently to
*this book may not carry that leverage* and *your signals cannot be combined*
can still tell them apart — a leverage target is refusable for a book whose
signals weighted up perfectly, so the two facts are genuinely different and a
vocabulary that merged them would make a caller re-inspect something it
cannot tell apart.
"""

from __future__ import annotations

__all__ = [
    "AgentAuthoredModificationError",
    "BookChangeRequestError",
    "BookConstructionError",
    "ChangelogEntryRequestError",
    "FinalWeightsRequestError",
    "LeverageRequestError",
    "LeverageTargetError",
    "LimitBreachError",
    "LimitRequestError",
    "MissingChangelogEntryError",
    "OrderLayerOutputError",
    "VolatilityTargetError",
    "VolatilityTargetRequestError",
]


class BookConstructionError(Exception):
    """The book member's base refusal — a signal could not be weighted into a
    book, a combined book could not be sized, or a leverage target the
    resulting book may not carry.

    Raised directly by :func:`book.combine` (and by the construction of a
    :class:`book.PromotedSignal` or :class:`book.CompositeBook` that the
    combiner would not itself produce) when the promoted signals cannot be
    weighted into a composite, and by
    :meth:`book.TargetWeights.weight` when a symbol the book does not cover is
    asked for under the same ``uncovered_symbol`` word.  Every message opens
    with a greppable one-word code — ``empty_book``, ``unnamed_signal``,
    ``duplicate_signal``, ``non_positive_ir``, ``non_finite_ir``,
    ``signal_without_scores``, ``non_finite_score`` or ``uncovered_symbol`` —
    and names the signal and, where relevant, the symbol.

    It is also the **base of the member's whole refusal surface**, which is
    the one-base-per-member shape the dreaming and regime members state for
    their own vocabularies: :class:`LeverageRequestError` (feature 308's ask)
    and :class:`LeverageTargetError` (feature 308's verdict) descend from it,
    :class:`VolatilityTargetRequestError` (feature 303's ask) and
    :class:`VolatilityTargetError` (feature 303's verdict) join them,
    :class:`LimitRequestError` (feature 304's ask) and
    :class:`LimitBreachError` (feature 304's verdict) join them too,
    :class:`FinalWeightsRequestError` (feature 305's ask) and
    :class:`OrderLayerOutputError` (feature 305's verdict) join them,
    :class:`BookChangeRequestError` (feature 306's ask) and
    :class:`AgentAuthoredModificationError` (feature 306's verdict) join them,
    and :class:`ChangelogEntryRequestError` (feature 307's ask) and
    :class:`MissingChangelogEntryError` (feature 307's verdict) join them as
    well, so a caller that must refuse rather than rank catches this one class
    and catches the act's, the cap's, the guard's, the limits', the published
    set's and the companion's failures with it.  A caller that has to *react*
    differently to *your signals cannot be combined*, *this book expresses no
    view to size*, *this book may not carry that leverage*, *these weights
    breach a limit*, *no book reached the orders*, *this change to the
    construction was authored by an agent* and *this change had no changelog
    entry* catches the specific siblings instead — see each for why the
    distinction is worth a class.  The classes are siblings rather than
    aliases because the facts are genuinely different: a leverage target is
    refusable for a book whose signals weighted up perfectly, a flat composite
    is refusable though both volatility figures were perfectly well stated, a
    breaching book is refusable though both limits were perfectly well stated,
    a value carrying no book is refusable though nothing else was involved, an
    agent-authored change is refusable though perfectly well stated, and a
    change whose entry is absent is refusable though the entry field was
    perfectly well formed — it was simply not handed.
    """


class LeverageRequestError(BookConstructionError):
    """The leverage cap could not be asked for as the caller asked for it.

    app_spec.xml, "Portfolio Book Construction", feature 308: *System rejects
    a leverage target above one quarter of the Kelly fraction implied by the
    book Sharpe and volatility.*  This class is the *ask* face of that
    sentence and never the judgment: it refuses a leverage target that is not
    a finite real of zero or more, a book Sharpe that is not a finite real, or
    a book volatility that is not a finite strictly positive real — the
    figures :func:`book.leverage_cap` and
    :func:`book.rejects_overleveraged_target` are computed from — **before**
    any fraction is formed, the ordering every verdict and store in this
    workspace states.

    **What it deliberately does not refuse: a non-positive Sharpe.**  A
    losing book's Sharpe is a measurement, not a malformed ask, and the
    honest consequence — a Kelly fraction at or below zero, and therefore a
    cap that admits no *long* leverage (though it still admits the flat book,
    the admissible set being the cap intersected with leverage zero-and-up) —
    is the answer :func:`book.leverage_cap` returns and the refusal
    :class:`LeverageTargetError` states in the book's own terms.  Refusing
    the Sharpe here would hide the book's figure behind a validation and
    leave a caller unable to tell *no long leverage is admissible* from
    *your ask named no figure*.

    **No code word, and deliberately.**  Feature 308's sentence mandates no
    token (it names its subject in prose), and every message here opens with
    its subject — the figure, its type and what it is for — the shape
    :class:`dreaming.errors.CapRequestError` states for its own pair, so a
    reader is told *what to fix* rather than handed a token to grep for.  The
    one code the sentence's path carries is
    :class:`LeverageTargetError`'s, on the verdict alone.

    **Why it is its own class rather than the base alone.**  The repair
    differs.  A bare :class:`BookConstructionError` means *your signals
    cannot be combined — fix the signals*; this one means *your ask named no
    figure the cap can be computed from — fix the ask*, and the two are not
    the same instruction.  A caller that must react differently to them can
    tell them apart by class; a caller that refuses book work wholesale still
    catches one class, the base this descends from.
    """


class LeverageTargetError(BookConstructionError):
    """The leverage target is above one quarter of the book's Kelly fraction.

    app_spec.xml, "Portfolio Book Construction", feature 308: *System rejects
    a leverage target above one quarter of the Kelly fraction implied by the
    book Sharpe and volatility.*  This class is the judgment that sentence
    mints — the one refusal on the cap's path that is a *verdict* rather than
    a validation — and it is raised by
    :func:`book.rejects_overleveraged_target` when a well-formed target sits
    above a well-formed cap.  Its message opens with the greppable code
    :data:`book.OVERLEVERAGE_CODE` (``leverage_above_quarter_kelly``).

    **Why the quarter, stated where the refusal is caught.**  The Kelly
    fraction ``f* = S/σ`` is Appendix B's line and is estimated from a Sharpe
    — a figure docs/alpha-engine-prd.md §1.2 states the worth of exactly:
    *"A backtest Sharpe of 4.0 is a noisy, biased, adversarially exploitable
    estimate."*  Betting the full ``f*`` bets a point estimate as though it
    were the truth, so the table states the discount itself — *"use ≤ ¼
    Kelly"* — and this class is the refusal that enforces it.

    **Its repair is its own, which is why it is its own class.**  *Lower the
    target to one quarter Kelly or below* — or, where the cap itself is not
    positive (a book whose measured Sharpe is non-positive), the repair is
    the only one that exists on it: *hold the book flat, and re-ask once the
    measured Sharpe is positive*.  The two classes a caller could otherwise
    catch this as both name repairs that are wrong here:
    :class:`LeverageRequestError` means *your ask named no figure* (the
    target is perfectly well formed and the cap is perfectly well defined —
    it is simply smaller), and the bare :class:`BookConstructionError` means
    *your signals cannot be combined* (they combined; the resulting book is
    real and its Sharpe is what capped it).  Folding these together would
    make a caller that must react differently to *this book may not carry
    that leverage* and *your ask was malformed* catch one class and
    re-inspect something it cannot tell apart, which is the failure this
    vocabulary is split to prevent.

    **The edge is the sentence's own word.**  A target *at* the cap is
    admitted — Appendix B's *"use ≤ ¼ Kelly"* is inclusive on the admitted
    side — so this class is raised strictly above it.
    """


class VolatilityTargetRequestError(BookConstructionError):
    """The volatility target could not be asked for as the caller asked for it.

    app_spec.xml, "Portfolio Book Construction", feature 303: *System applies
    volatility targeting to the combined book, which returns weights scaled to
    a configured annualized volatility.*  This class is the *ask* face of that
    sentence and never the judgment: it refuses a book that carries no
    ``scores`` mapping of symbol to composite target score, a book covering no
    symbols, a symbol or score that cannot be part of such a book, a book
    volatility that is not a finite **strictly positive** real, and a
    configured target that is not a finite real of **zero or more** —
    **before** any book is normalized or scaled, the ordering every verdict
    and act in this workspace states.

    It is raised by :func:`book.apply_volatility_target` and by the
    construction of a :class:`book.TargetWeights` that the act would not
    itself produce, because that record's own self-check states the same facts
    about the same fields.

    **What it deliberately does not refuse: a well-formed but awkward
    figure.**  A *zero* target — a deployment asking for no risk — is a
    perfectly well-formed configuration whose honest answer is a flat book
    (``scale == 0.0``, every weight ``0.0``), the reading feature 308 gives a
    zero Sharpe; a target *above* the book's volatility is a book levered up
    to its configured risk, which is what targeting is for; and a book whose
    composite scores are all zero is a *judgment* about the book rather than a
    malformed ask, so it is :class:`VolatilityTargetError`'s alone.  Refusing
    any of these here would report a deployment's own decision, or its
    book's own view, as a validation failure.

    **No code word, and deliberately.**  Feature 303's sentence mandates no
    token (it names its subject in prose), and every message here opens with
    its subject — the field, its type and what it is for — the shape
    :class:`LeverageRequestError` and :class:`BookChangeRequestError` state for
    their own pairs, so a reader is told *what to fix* rather than handed a
    token to grep for.  The one code the sentence's path carries is
    :class:`VolatilityTargetError`'s, on the judgment alone.

    **Why it is its own class rather than the base alone.**  The repair
    differs.  A bare :class:`BookConstructionError` means *your signals cannot
    be combined — fix the signals*; this one means *your ask named no book or
    no figure the act can scale — fix the ask*, and the two are not the same
    instruction.  A caller that must react differently to them can tell them
    apart by class; a caller that refuses book work wholesale still catches
    one class, the base this descends from.

    **Why the ask's two figures are validated here rather than shared with
    feature 308's.**  Feature 308 states *the same kind of fact* about the
    book's volatility for its Kelly fraction, and the temptation is one
    validator serving both.  It is refused deliberately: a shared helper
    raising the other feature's error type would defeat a caller's ``except``
    — the error-vocabulary trap this workspace states at its member seams —
    so each feature spells its own validator over its own class, and the two
    cannot start reporting each other's subjects.
    """


class VolatilityTargetError(BookConstructionError):
    """The combined book expresses no view to scale — feature 303's judgment.

    app_spec.xml, "Portfolio Book Construction", feature 303: *System applies
    volatility targeting to the combined book, which returns weights scaled to
    a configured annualized volatility.*  This class is the judgment that
    sentence mints — the one refusal on the act's path that is a *verdict*
    rather than a validation — and it is raised by
    :func:`book.apply_volatility_target` when a wholly well-stated book's
    composite target scores are **all zero**.  Its message opens with the
    greppable code :data:`book.FLAT_BOOK_CODE` (``flat_book``).

    **Why the boundary is there, stated where the refusal is caught.**  The
    act's first step turns the combined book into a book by normalizing it to
    one unit of gross exposure — ``w_raw = score_s / Σ_t |score_t|`` — which
    is what makes the composite's free *sign and scale* (PRD §3) into an
    exposure the order layer can hold.  A composite scored at zero everywhere
    has a gross score of exactly ``0.0``, so that normalization is a division
    by exactly nothing: the weights are undefined, not flat.  Answering an
    all-zero weight set instead would counterfeit a book from no view — the
    same perpetration feature 301 refuses when it declines to zero-fill a
    signal that carries no score for a symbol — and it would hand the order
    layer a *decision to hold nothing* that no signal made.

    **Its repair is its own, which is why it is its own class.**  *Hand a
    composite that expresses a view* — this act fabricates none and holds no
    weight to fall back on.  The two classes a caller could otherwise catch
    this as both name repairs that are wrong here:
    :class:`VolatilityTargetRequestError` means *your ask named no book or no
    figure* (the book is perfectly well stated and the figures perfectly well
    formed — the composite simply has no direction), and the bare
    :class:`BookConstructionError` means *your signals cannot be combined*
    (they combined; the composite is real and it is flat).  Folding these
    together would make a caller that must react differently to *this book
    expresses no view* and *your ask was malformed* catch one class and
    re-inspect something it cannot tell apart, which is the failure this
    vocabulary is split to prevent.

    **A configured target of zero is not this refusal.**  That is a deployment
    asking for no risk, and it is answered — a scale of ``0.0`` and a book of
    zero weights — because the flat book there is the *configuration's* own
    consequence rather than a view this act invented.  The difference is the
    whole reason the two zeros are separate codes' worth of meaning: one is a
    divisor that is nothing, the other a level the caller chose.
    """


class BookChangeRequestError(BookConstructionError):
    """The authorship guard could not be asked for as the caller asked for it.

    app_spec.xml, "Portfolio Book Construction", feature 306: *System keeps
    book construction human-authored and version-controlled, which rejects
    any agent-authored modification to it.*  This class is the *ask* face of
    that sentence and never the judgment: it refuses a change record that
    cannot be stated at all — a subject or author that is not a non-empty
    string, an ``author_kind`` outside the declared vocabulary
    (near-misses like ``"Human"`` and unknowns like ``"ci-bot"``, refused
    here rather than judged agent-authored), or a revision that is not the
    full commit id (a branch, a tag, ``HEAD``, a short id, an uppercase
    spelling, or no commit at all) — **before** any authorship is judged,
    the ordering every verdict and store in this workspace states.

    **What it deliberately does not refuse: a declared agent kind.**  A
    change authored by the discovery loop or the dreaming reviser is
    perfectly well *stated* — its subject, author, kind and commit are all
    real facts — and refusing it here would hide the sentence's own
    judgment behind a validation, leaving a caller unable to tell *the
    search reached for the construction* (the refusal the operator greps
    for) from *your change record named no commit*.  The judgment is
    :class:`AgentAuthoredModificationError`'s alone.

    **No code word, and deliberately.**  Feature 306's sentence mandates no
    token (it names its subject in prose), and every message here opens
    with its subject — the field, its type and what it is for — the shape
    :class:`LeverageRequestError` states for its own pair and
    :class:`dreaming.errors.CapRequestError` for its own, so a reader is
    told *what to fix* rather than handed a token to grep for.  The one
    code the
    sentence's path carries is
    :class:`AgentAuthoredModificationError`'s, on the judgment alone.

    **Why it is its own class rather than the base alone.**  The repair
    differs.  A bare :class:`BookConstructionError` means *your signals
    cannot be combined — fix the signals*; this one means *your change
    record could not be stated — fix the record*, and the two are not the
    same instruction.  A caller that must react differently to them can
    tell them apart by class; a caller that refuses book work wholesale
    still catches one class, the base this descends from.
    """


class AgentAuthoredModificationError(BookConstructionError):
    """The change was authored by an agent — feature 306's judgment.

    app_spec.xml, "Portfolio Book Construction", feature 306: *System keeps
    book construction human-authored and version-controlled, which rejects
    any agent-authored modification to it.*  This class is the judgment
    that sentence mints — the one refusal on the guard's path that is a
    *verdict* rather than a validation — and it is raised by
    :func:`book.rejects_agent_authored_modification` when a wholly
    well-stated change's author kind is not the human one.  Its message
    opens with the greppable code
    :data:`book.AGENT_MODIFICATION_CODE` (``agent_authored_modification``).

    **Why the boundary is there, stated where the refusal is caught.**
    docs/alpha-engine-prd.md §C8 closes the construction's own section
    with it: *"Version-controlled, human-authored, explicitly outside the
    search space.  Changing it is a human decision with a changelog entry,
    not a discovery."*  This system already contains a lawful automated
    author — the dreaming reviser revises *policy* source, and the sweep
    commits its selections — and the one thing that machinery may never
    touch is the construction that weights what it finds: a search allowed
    to improve its own weighting function has stopped being measured by
    it.  This class is the refusal that enforces §C8's line.

    **Its repair is its own, which is why it is its own class.**  *A human
    makes the change* — the same subject, decided by a person, committed
    under version control (with the changelog entry feature 307 requires).
    There is no other repair, and deliberately no relabelling one: the
    author kind is not a parameter to talk the module out of, because an
    author vocabulary that could be widened by its caller would be the
    whole guard gone by configuration.  The other classes a caller could
    catch this as both name repairs that are wrong here:
    :class:`BookChangeRequestError` means *your change record could not be
    stated* (it was stated perfectly — it was just authored by an agent),
    and the bare :class:`BookConstructionError` means *your signals cannot
    be combined* (no signals are involved).  Folding these together would
    make a caller that must react differently to *the search reached for
    the construction* and *your record named no commit* catch one class
    and re-inspect something it cannot tell apart, which is the failure
    this vocabulary is split to prevent.

    **The refusal is over any agent-authored modification.**  Every
    declared agent kind lands here — ``agent``, ``discovery``,
    ``dreaming``, ``optimizer``, ``worker`` — and nothing outside the one
    human kind is admitted by any route, so the refusal is complete in the
    sentence's own word: *any*.
    """


class ChangelogEntryRequestError(BookConstructionError):
    """The companion could not be asked for as the caller asked for it.

    app_spec.xml, "Portfolio Book Construction", feature 307: *System requires
    a changelog entry accompanying every book construction change, which
    returns a validation failure when absent.*  This class is the *ask* face of
    that sentence and never the judgment: it refuses a change that is not
    present to be accompanied, or an entry that cannot be stated at all — a
    subject or body that is not a non-empty string — **before** any absence is
    judged, the ordering every verdict and store in this workspace states.

    **What it deliberately does not refuse: an absent entry.**  A change whose
    entry was simply not handed is perfectly well *asked for* — the change and
    the (absent) entry are real facts — and refusing it here would hide the
    sentence's own judgment behind a validation, leaving a caller unable to
    tell *the change had no changelog entry* (the refusal the operator greps
    for) from *your entry named no body*.  The judgment is
    :class:`MissingChangelogEntryError`'s alone.

    **No code word, and deliberately.**  Feature 307's sentence mandates no
    token (it names its subject in prose), and every message here opens with
    its subject — the field, its type and what it is for — the shape
    :class:`BookChangeRequestError` states for its own pair, so a reader is
    told *what to fix* rather than handed a token to grep for.  The one code
    the sentence's path carries is :class:`MissingChangelogEntryError`'s, on
    the verdict alone.

    **Why it is its own class rather than the base alone.**  The repair
    differs.  A bare :class:`BookConstructionError` means *your signals cannot
    be combined — fix the signals*; this one means *your entry (or change)
    could not be stated — state it*, and the two are not the same instruction.
    A caller that must react differently to them can tell them apart by class;
    a caller that refuses book work wholesale still catches one class, the base
    this descends from.
    """


class MissingChangelogEntryError(BookConstructionError):
    """The change had no changelog entry beside it — feature 307's judgment.

    app_spec.xml, "Portfolio Book Construction", feature 307: *System requires
    a changelog entry accompanying every book construction change, which
    returns a validation failure when absent.*  This class is the judgment that
    sentence mints — the one refusal on the companion's path that is a *verdict*
    rather than a validation — and it is raised by
    :func:`book.requires_changelog_entry` when a present change's entry is
    absent.  Its message opens with the greppable code
    :data:`book.MISSING_CHANGELOG_ENTRY_CODE` (``missing_changelog_entry``).

    **Why the boundary is presence, not content, stated where the refusal is
    caught.**  docs/alpha-engine-prd.md §C8 closes the construction's own
    section with it: *"Changing it is a human decision with a changelog entry,
    not a discovery."*  The entry is the human's own document — the record of
    what changed and why — and this package validates no changelog prose (what
    the entry *says* is none of its business), so the entry is admitted as
    *present* when it is a well-stated :class:`book.ChangelogEntry` and refused
    as *absent* when it is not there at all.  This class is the refusal that
    enforces §C8's *"with a changelog entry"*: a change lands only when its
    entry accompanies it.

    **Its repair is its own, which is why it is its own class.**  *A human
    accompanies the change with the changelog entry it requires* — the same
    subject, decided by a person, committed under version control, with the
    entry that documents it.  There is no fabrication repair — this module does
    not invent the human's own document — and the other classes a caller could
    catch this as both name repairs that are wrong here:
    :class:`ChangelogEntryRequestError` means *your entry could not be stated*
    (no entry was handed at all, or it was stated badly), and the bare
    :class:`BookConstructionError` means *your signals cannot be combined* (no
    signals are involved).  Folding these together would make a caller that
    must react differently to *the change had no entry beside it* and *your
    entry was malformed* catch one class and re-inspect something it cannot
    tell apart, which is the failure this vocabulary is split to prevent.

    **The refusal names the change.**  Every refusal states the change the
    entry was meant to accompany — its subject, its author, its kind, its
    revision — so the operator can see *which change* meant to land without its
    record.
    """


class LimitRequestError(BookConstructionError):
    """The position and concentration limits could not be asked for as asked.

    app_spec.xml, "Portfolio Book Construction", feature 304: *System applies
    per-position and concentration limits, which rejects a target weight
    breaching either bound.*  This class is the *ask* face of that sentence and
    never the judgment: it refuses a value that carries no ``weights`` mapping
    of symbol to weight, target weights covering no symbols, a symbol or weight
    that cannot be part of such a book, and a limit that is not a finite real
    of **zero or more** — **before** either bound is read, the ordering every
    verdict and act in this workspace states.

    It is raised by :func:`book.is_breaching_limits` and
    :func:`book.rejects_breaching_target_weights` alike, because the predicate
    and the verdict settle the ask identically — the discipline feature 307's
    pair states for its own two spellings.

    **What it deliberately does not refuse: a zero limit, and a flat book.**  A
    limit of ``0`` — a deployment asking for no position, or for a book
    concentrated in nothing — is a perfectly well-formed risk appetite whose
    honest consequence is the flat book, the reading feature 308 gives a zero
    Sharpe and feature 303 gives a zero configured target: on a zero
    per-position limit only the flat book is admitted, and on a zero
    concentration limit only the flat book is admitted too (every book that
    holds something is strictly concentrated).  Refusing them here would report
    a deployment's own risk decision as a validation failure.  A book that
    breaches a bound is a *judgment* about the book rather than a malformed
    ask, so it is :class:`LimitBreachError`'s alone.

    **No code word, and deliberately.**  Feature 304's sentence mandates no
    token (it names its subject in prose), and every message here opens with
    its subject — the field, its type and what it is for — the shape
    :class:`LeverageRequestError` and :class:`VolatilityTargetRequestError`
    state for their own pairs, so a reader is told *what to fix* rather than
    handed a token to grep for.  The codes the sentence's path carries are
    :class:`LimitBreachError`'s, on the judgment alone.

    **Why it is its own class rather than the base alone.**  The repair
    differs.  A bare :class:`BookConstructionError` means *your signals cannot
    be combined — fix the signals*; this one means *your ask named no book or
    no limit the bounds can be read against — fix the ask*, and the two are not
    the same instruction.  A caller that must react differently to them can
    tell them apart by class; a caller that refuses book work wholesale still
    catches one class, the base this descends from.

    **Why the limits are validated here rather than shared with feature 303's
    or feature 308's.**  All three features validate *a finite real* for
    figures of their own, and the temptation is one shared validator.  It is
    refused deliberately: a shared helper raising another feature's error type
    would defeat a caller's ``except`` — the error-vocabulary trap this
    workspace states at its member seams — and the policies are not even the
    same (that act's volatility is strictly positive, that cap's Sharpe is
    free-signed, these limits are zero-or-more), so each feature spells its own
    validator over its own class and the three cannot start reporting each
    other's subjects.
    """


class LimitBreachError(BookConstructionError):
    """A target weight breaches a position or concentration bound — 304's judgment.

    app_spec.xml, "Portfolio Book Construction", feature 304: *System applies
    per-position and concentration limits, which rejects a target weight
    breaching either bound.*  This class is the judgment that sentence mints —
    the one refusal on the limits' path that is a *verdict* rather than a
    validation — and it is raised by
    :func:`book.rejects_breaching_target_weights` when a wholly well-stated
    book's target weights breach either bound.  Its message opens with the
    greppable code of the bound that was breached:
    :data:`book.PER_POSITION_LIMIT_CODE` (``position_above_limit``) or
    :data:`book.CONCENTRATION_LIMIT_CODE` (``concentration_above_limit``).

    **Two codes on one class, and deliberately.**  The two bounds are two
    repairs — *shrink that position* against *spread the book* — and each is
    greppable, so an operator's log line lands on the bound they have to fix;
    but the *caller's position* is the same either way (the weights it was
    about to hand the order layer are outside the deployment's limits, and the
    repair is always to hand weights inside them), which is the test the
    router's limiter states for gathering two faults under one class.  A
    caller that must react differently to the two catches one class and greps
    the code; a caller that refuses book work wholesale catches the base.

    **Why the bounds are there, stated where the refusal is caught.**
    docs/alpha-engine-prd.md §C8 puts the step in the construction's own chain
    — *"Signal book → IR-weighted combination with shrinkage → volatility
    targeting → position and concentration limits → orders"* — and
    docs/nullius-tech-architecture.md §13.1 states it as the live path's book
    manager.  §C8 names the step and states no figure for either bound: the
    documents state the *form* of the chain, a discount on a Kelly fraction and
    the form of a bar, but nowhere how large a position may be or how
    concentrated a book may get.  Those are a deployment's own risk decisions,
    so they arrive as required keywords of the call, and this class is the
    refusal that enforces them.

    **Its repair is its own, which is why it is its own class.**  *Hand target
    weights inside the bounds* — this module scales nothing down, re-weights
    nothing and clamps nothing, because reshaping a caller's book would be this
    member *sizing* it rather than bounding it (feature 308's stance on the
    same member's other bound).  The two classes a caller could otherwise catch
    this as both name repairs that are wrong here:
    :class:`LimitRequestError` means *your ask named no book or no limit* (the
    weights are perfectly well stated and the limits perfectly well formed —
    the book is simply outside them), and the bare
    :class:`BookConstructionError` means *your signals cannot be combined*
    (they combined, feature 303 sized them, and the resulting book is real and
    breaching).  Folding these together would make a caller that must react
    differently to *these weights breach a limit* and *your ask was malformed*
    catch one class and re-inspect something it cannot tell apart, which is the
    failure this vocabulary is split to prevent.

    **The edge is the sentence's own word.**  A target weight exactly *at* a
    limit is admitted — the bound is a budget, and spending it exactly is
    spending within it — so this class is raised strictly above it, the edge
    feature 308 states for its cap and Appendix B's *"use ≤ ¼ Kelly"* states
    for the quarter.
    """


class FinalWeightsRequestError(BookConstructionError):
    """The final target weights could not be published as the caller asked.

    app_spec.xml, "Portfolio Book Construction", feature 305: *System returns
    final target weights as the only output consumed by the order layer.*  This
    class is the *ask* face of that sentence and never the judgment: it refuses
    the value the caller means to publish as the construction's output — a value
    carrying no ``weights`` mapping, a non-mapping, a published set covering no
    symbols, a blank symbol name, a weight that is not a finite real, and a
    value meant for the order layer that declares itself no published book —
    **before** any instruction reaches the orders, the ordering every verdict
    and act in this workspace states.

    It is raised by :func:`book.final_target_weights`, by
    :func:`book.is_only_output` and by :func:`book.assert_only_output` when the
    value meant for the orders is not a published book, and by the construction
    of a :class:`book.FinalTargetWeights` that the act would not itself produce,
    because that record's own self-check states the same facts about the same
    fields through the same reader.

    **The code is carried, and it is one word for several failures.**  Every
    message where the value is not a book at all opens with
    :data:`book.NO_BOOK_CODE` (``no_book``), because those failures share one
    repair — *hand a book* — and an operator greps one word to learn that no
    instruction reached the order layer.  A message about a symbol or a weight
    *inside* an otherwise real book carries no code, the reason
    :class:`LimitRequestError` gives for its own: a malformed key or magnitude
    names its subject in its first words, and a token there would hand a reader
    a developer's word for a fact they can simply state.

    **What it deliberately does not refuse: a book held flat.**  Every weight
    ``0.0`` — feature 303's own answer for a configured target of zero, and a
    set feature 304 admits at every limit of zero or more — is a decision the
    construction is entitled to publish.  *Hold nothing* is an instruction,
    where a value carrying no weights, an empty book and a malformed weight are
    the *absence* of one.  Refusing the flat book here would report a risk
    appetite's own consequence as a malformed ask.

    **Why it is its own class rather than the base alone.**  The repair differs.
    A bare :class:`BookConstructionError` means *your signals cannot be
    combined — fix the signals*; this one means *what you meant to hand the
    order layer is not a book — publish the construction's own book*, and the
    two are not the same instruction.  A caller that must react differently to
    them can tell them apart by class; a caller that refuses book work wholesale
    still catches one class, the base this descends from.
    """


class OrderLayerOutputError(BookConstructionError):
    """A second record claimed the order layer's output — feature 305's judgment.

    app_spec.xml, "Portfolio Book Construction", feature 305: *System returns
    final target weights as the only output consumed by the order layer.*  This
    class is the judgment that sentence mints — the one refusal on the
    publication path that is a *verdict* rather than an ask's own fact — and it
    is raised by :func:`book.is_only_output` and
    :func:`book.assert_only_output` when the instruction meant for the order
    layer carries a second record declaring itself a published final weight set
    beside the one the caller handed over.  Its message opens with the greppable
    code :data:`book.ANNEXED_RECORD_CODE` (``annexed_record``).

    **Why the boundary is there, stated where the refusal is caught.**  §C8's
    chain ends at *"orders"* and docs/nullius-tech-architecture.md §13.1 names
    the same last link as the *"target weights"*; §13.2's execution engine is
    the process on the other side of that seam, and it holds a book.  A chain
    whose every step returned its own record would hand that engine three or
    four things to reconcile and it would have to decide which is the book —
    the construction's job performed one layer down, with no bound re-run and no
    document saying which record wins.  This class is the refusal that enforces
    the sentence's *only*.

    **The construction's working is not this refusal.**  The composite, the
    gross book, the scale and the target weights are figures a caller may
    legitimately hold beside the published set — those records are where the
    construction's arithmetic belongs.  What is refused is a second *published*
    set: two records both declaring themselves the order layer's instruction.

    **Its repair is its own, which is why it is its own class.**  *Hand the
    order layer exactly one published set* — this module reconciles nothing and
    chooses nothing, because picking between two instructions would be this
    member deciding which book the orders hold.  The two classes a caller could
    otherwise catch this as both name repairs that are wrong here:
    :class:`FinalWeightsRequestError` means *what you handed over is not a book*
    (both sets are perfectly well stated), and the bare
    :class:`BookConstructionError` means *your signals cannot be combined* (they
    combined; the construction is real and it published more than one
    instruction).  Folding these together would make a caller that must react
    differently to *two instructions reached the orders* and *your ask named no
    book* catch one class and re-inspect something it cannot tell apart, which
    is the failure this vocabulary is split to prevent.
    """
