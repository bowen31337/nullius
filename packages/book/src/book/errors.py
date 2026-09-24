"""The book combiner's refusal vocabulary — features 301, 306 and 308.

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
    "LeverageRequestError",
    "LeverageTargetError",
    "MissingChangelogEntryError",
]


class BookConstructionError(Exception):
    """The book member's base refusal — a signal could not be weighted into a
    book, or a leverage target the resulting book may not carry.

    Raised directly by :func:`book.combine` (and by the construction of a
    :class:`book.PromotedSignal` or :class:`book.CompositeBook` that the
    combiner would not itself produce) when the promoted signals cannot be
    weighted into a composite.  Every message opens with a greppable
    one-word code — ``empty_book``, ``unnamed_signal``, ``duplicate_signal``,
    ``non_positive_ir``, ``non_finite_ir``, ``signal_without_scores``,
    ``non_finite_score`` or ``uncovered_symbol`` — and names the signal and,
    where relevant, the symbol.

    It is also the **base of the member's whole refusal surface**, which is
    the one-base-per-member shape the dreaming and regime members state for
    their own vocabularies: :class:`LeverageRequestError` (feature 308's ask)
    and :class:`LeverageTargetError` (feature 308's verdict) descend from it,
    :class:`BookChangeRequestError` (feature 306's ask) and
    :class:`AgentAuthoredModificationError` (feature 306's verdict) join them,
    and :class:`ChangelogEntryRequestError` (feature 307's ask) and
    :class:`MissingChangelogEntryError` (feature 307's verdict) join them too,
    so a caller that must refuse rather than rank catches this one class and
    catches the cap's, the guard's and the companion's failures with it.  A
    caller that has to *react* differently to *your signals cannot be
    combined*, *this book may not carry that leverage*, *an agent authored this
    change to the construction* and *this change had no changelog entry*
    catches the specific siblings instead — see each for why the distinction is
    worth a class.  The classes are siblings rather than aliases because the
    facts are genuinely different: a leverage target is refusable for a book
    whose signals weighted up perfectly, an agent-authored change is refusable
    though perfectly well stated, and a change whose entry is absent is
    refusable though the entry field was perfectly well formed — it was simply
    not handed.
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
