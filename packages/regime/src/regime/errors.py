"""The regime member's error vocabulary.

One base class (:class:`RegimeError`) so a caller — the promotion gate, the
coverage endpoint, an operator script, a later feature in this category —
can catch every failure of this member's path with a single ``except``.
The subclasses split by *what the caller must do about it*, not by which
line of code raised, the discipline :mod:`discovery.errors`,
:mod:`bootstrap.errors` and :mod:`nulloracle.errors` state for their own
trees.

:class:`CoverageError` is the category's first class, and it carries the
three faces of feature 283's one act — *System persists a
``regime_coverage`` count per stratum*:

* the **ask** — a stratum that is not non-empty text, or a ``world_count``
  that is not a genuine non-negative integer (``True`` is not a count, a
  negative number of worlds is not a number of worlds, and a fractional
  world is not a world).  Nothing was read and nothing was written; the
  repair is to re-send the ask with values the feature's sentence is about.
* the **row** — a stored row too corrupt to be a coverage count: a
  ``world_count`` column holding something that is not a non-negative
  integer, or an ``updated_at`` the table declares ``NOT NULL`` carrying
  nothing.  SQLite's columns are dynamically typed, so a raw ``INSERT``
  from another tool can land anything in this table, and a ledger read
  that swallowed it would report a count nobody wrote.  The repair is to
  the *data*, not to the call: an operator reads the stratum every
  message of this face names.
* the **address** — a ``DATABASE_URL`` this member cannot speak (a
  non-SQLite scheme, a host in a SQLite URL, no path at all, or an
  in-memory database, which would die with the connection that opened it
  and take the ledger with it).  The repair is to point the deployment at
  the database the ledger lives in.

One class rather than three because the caller's position is the same in
all three cases: the count it asked to persist was not persisted, and the
next step is to read which of the three faces the message names.  That is
the same repair :class:`~discovery.errors.AttemptLogError` gathers under
one class for its own act, and the contrast with this member's future
classes is the reason the split rule is worth stating here: features 285
and 289 add *judgement* refusals (a promotion blocked on coverage, a
diversity claim refused on stratum count) whose repair is a decision about
evidence rather than a corrected re-ask, and they will sit **beside** this
class as siblings, not under it — the shape
:class:`~discovery.errors.IllegalThemeError` takes beside
:class:`~discovery.errors.CampaignPlanningError`, and for the same reason:
a well-formed ask that runs into a configured space or a judged threshold
is not a malformed one, and folding the two would put two different
repairs behind one ``except``.

This member deliberately does **not** raise
:class:`feature_store.regime_labeler.FullHistoryFitError`, even though the
labeler that assigns worlds to strata is the source of the names this
ledger keys on: the workspace contract is that no member imports another,
and a caller reading a labeler refusal out of a *coverage persist* would
look in the wrong module for the cause — the labeler refuses a fit
(feature 58's law), while this member refuses a *row*.  Different acts,
different vocabularies; the seam between them is the caller that holds
both, and ``packages/regime/tests/test_cross_member.py`` is what keeps the
stratum count the two agree on honest.
"""

from __future__ import annotations

__all__ = ["CoverageError", "RegimeError"]


class RegimeError(Exception):
    """Base class for every failure of the regime member's path."""


class CoverageError(RegimeError):
    """A coverage count could not be persisted as asked.

    Raised for the ask (a malformed stratum or count), for the row (a
    stored value too corrupt to be a coverage count) and for the address
    (a ``DATABASE_URL`` this member cannot speak) — the three faces of
    feature 283's one act, and the three repairs the module docstring
    states.  Every message names the stratum it is about where one is in
    question, so an operator's log line says which row of the ledger the
    refusal concerns.
    """
