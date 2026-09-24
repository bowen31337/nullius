"""The book combiner's refusal vocabulary — feature 301.

app_spec.xml, "Portfolio Book Construction", feature 301: *System combines
promoted signals by information-ratio weighting, which returns a single
composite target score per symbol.*  A combine can fail only because the
promoted signals it was handed cannot be weighted into a book, and this
module is the one place those failures are named.

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
"""

from __future__ import annotations

__all__ = ["BookConstructionError"]


class BookConstructionError(Exception):
    """A promoted signal could not be weighted into a book.

    Raised by :func:`book.combine` (and by the construction of a
    :class:`book.PromotedSignal` or :class:`book.CompositeBook` that the
    combiner would not itself produce) when the promoted signals cannot be
    weighted into a composite.  Every message opens with a greppable
    one-word code — ``empty_book``, ``unnamed_signal``, ``duplicate_signal``,
    ``non_positive_ir``, ``non_finite_ir``, ``signal_without_scores``,
    ``non_finite_score`` or ``uncovered_symbol`` — and names the signal and,
    where relevant, the symbol.  A caller that must refuse rather than rank
    catches this one class.
    """
