"""Feature 332's promotion seam: *when* a signal went out of sample.

app_spec.xml, "Forward-Test Tracking", feature 332: *System exposes POST
/forward/promote, which creates a forward_record carrying the promotion
timestamp.*  The timestamp is the one fact on that row this member does not
compute — it is the instant the promotion was decided, which is feature 293's
write into ``promotion_registry.decided_at``, read back by feature 300's
``promotion_window``.

**Why the instant is read and never derived.**  docs/alpha-engine-prd.md §5
Loop 3 and docs/nullius-tech-architecture.md §13.4 both put the whole value of
this table in that one column: *"a row that lost its promotion timestamp would
be an observation with no vintage, which is exactly the thing forward testing
exists to prevent."*  Three derived alternatives are each worse than the read:

* **The clock at hand.** ``utc_now()`` always answers, so the row always
  lands, and the boundary lands wherever the worker happened to run.  A worker
  that ran before the deciding evaluation finished would open the window
  *inside* in-sample data, and §5's *"data that did not exist when the
  hypothesis was formed"* would be false of the row that claims it.
* **The pre-registration's instant.** ``promotion_registry.
  pre_registered_at`` is *before* the evaluation by construction — that is
  §13 item 7's ordering — so a window opened there would begin measuring on
  data that existed when the hypothesis was formed.  It is the one instant
  ``0108``'s docstring says the row must not carry.
* **The criteria hash's horizon.**  The registry row holds the *hash* of the
  criteria, and sha256 is one-way: ``min_forward_days`` (feature 291's sixth
  criterion) cannot be recovered from it.  That is why feature 300 takes the
  horizon as a caller-supplied keyword, and why feature 332 takes it the same
  way.

So the instant arrives from the member that owns it.  This module is the whole
of that reaching: a **duck-checked, lazily-resolved seam** over
``promotion.promotion_window`` — resolved through
``importlib.import_module("promotion")`` at *call* time, the move
:mod:`replay.dependencies` makes toward ``is_replaying`` and
:mod:`dreaming.select` makes toward §7's blend, and for the same two reasons:
a member never imports another member (so this package's ``pyproject.toml``
keeps its one-dependency shape), and the loader imports a member under a
synthetic name — so the *callable* is what is wanted, never a class or a
module identity.

**The resolution is a call and not a check.**  What this module asks of the
promotion member is the one verb the act needs, ``promotion_window``, and it
is asked for at the moment the record is opened rather than at import.  A
deployment that composed no promotion member — or composed one whose module
carries no such verb — has no promotion instant to read, and that is a
refusal by name rather than a silent default: see
:class:`~forward.errors.ForwardPromotionError`, whose message names the repair
in feature 291's and feature 293's own terms.

**The refusal is translated at the seam, and the translation is one-way.**
Feature 300 raises :class:`~promotion.errors.PromotionWindowError` for a node
nobody registered, a row still open, and a row unreadable as a decision.  All
three arrive at a forward caller as :class:`~forward.errors.
ForwardPromotionError`, because a caller's ``except ForwardError`` guarding a
forward record must not be defeated by a neighbouring member's vocabulary —
and because the *repair* is one repair in all three cases from where this
member stands: nothing about the record can be written until the promotion has
an instant.

**Nothing here writes, and nothing here decides.**  This module spells no
``INSERT``, opens no connection and holds no cursor; it calls one function and
hands back its value.  Whether the signal *stands* is the deciding
evaluation's verdict (feature 292's comparison is the mismatch check, and it
is not this module's to run); whether the epoch has budget is feature 294's
count; and whether the window is still open is feature 300's own arithmetic,
asked of the value this module returns.  Feature 332's whole act is: read the
instant, stamp the row.
"""

from __future__ import annotations

import importlib
from typing import Any

from .errors import FORWARD_PROMOTION_ERROR_CODE, ForwardPromotionError

__all__ = [
    "PROMOTION_MEMBER",
    "PROMOTION_WINDOW_VERB",
    "read_promotion_window",
]

#: The workspace member the promotion instant is read from.  Spelled once so
#: the two places that name it — the resolution and the refusal's message —
#: cannot drift apart, and named as a *string* rather than imported because a
#: member never imports another member.
PROMOTION_MEMBER = "promotion"

#: The one verb this seam needs off that member.  Feature 300's module-level
#: spelling, which resolves the decision store from ``database_url`` else
#: ``DATABASE_URL`` and answers a window whose ``opened_at`` is feature 293's
#: stamp.  Named as a constant for the reason every seam verb in this
#: workspace is: a rename on the far side is then one literal to grep for,
#: and the refusal below names the verb it could not find.
PROMOTION_WINDOW_VERB = "promotion_window"


def _promotion_member() -> Any:
    """The promotion member's own namespace, or ``None`` when it is absent.

    Reached through ``importlib.import_module("promotion")`` — the way
    :mod:`replay.dependencies` reaches ``is_replaying``, **not** through
    ``app.modules.promotion``, whose single question is *what is the composed
    pre-registration registry?* and which answers nothing about a window.
    Resolved inside the function so this module stays import-cheap and the
    factory's scan — which imports this package to fire its ``@register`` —
    pays nothing for a module it may never use.

    ``None`` for a member that is not scanned and for one that cannot be
    imported, which are the same fact for this seam: there is no instant to
    read.  Caught broadly because the import may fail for reasons this module
    cannot enumerate (a synthetic module name, a partially scanned workspace,
    a member whose own imports are unsatisfied), and none of them is a reason
    a *forward* write should fail with an opaque ``ImportError`` — the caller
    is owed a refusal that names the repair, which is what
    :func:`read_promotion_window` raises.
    """
    try:
        return importlib.import_module(PROMOTION_MEMBER)
    except Exception:  # noqa: BLE001 - absence is the fact this returns
        return None


def _promotion_window_verb() -> Any:
    """Feature 300's ``promotion_window`` off the promotion member, or ``None``.

    Read as a *callable* rather than checked as a class, for the reason the
    member's own endpoints state: the loader imports a member under a
    synthetic module name, so a composed sibling is structurally identical but
    never the same object a direct import yields, and any identity check would
    refuse the very seam the composition hands out.
    """
    member = _promotion_member()
    if member is None:
        return None
    verb = getattr(member, PROMOTION_WINDOW_VERB, None)
    return verb if callable(verb) else None


def read_promotion_window(
    node_id: Any,
    *,
    forward_days: Any,
    database_url: str | None = None,
    env: Any = None,
) -> Any:
    """The forward window a promotion opened, read through the promotion member.

    The whole of feature 332's dependency, in one call.  The arguments are
    passed straight through to feature 300's own spelling — the node, the
    horizon the caller registered, an explicit ``database_url`` if the caller
    holds one, and the mapping the store's resolution order reads
    ``DATABASE_URL`` out of — so this seam adds no resolution rule of its own
    and cannot disagree with the member that owns the read.

    The return value is feature 300's :class:`~promotion.forward.
    PromotionWindow` for everything this member needs: ``opened_at`` is the
    promotion instant feature 332's row carries, and ``closes_at`` /
    ``open_at`` / ``elapsed_days`` are the questions features 333-339 will ask
    of the same value.  It is deliberately **not** narrowed to a tuple or a
    bare datetime here: narrowing would be this module restating the shape of
    another member's value, which is the second spelling the seam exists to
    avoid.

    Raises :class:`~forward.errors.ForwardPromotionError` for both halves of
    the seam's absence — no ``promotion`` member to reach, no
    ``promotion_window`` verb on it — and for every refusal the read itself
    raises, since from where this member stands all of them mean the same
    thing: *this promotion has no instant, and the repair is the promotion
    pipeline's*.
    """
    verb = _promotion_window_verb()
    if verb is None:
        raise ForwardPromotionError(
            f"{FORWARD_PROMOTION_ERROR_CODE}: the promotion instant cannot be "
            f"read — the {PROMOTION_MEMBER!r} member exposes no "
            f"{PROMOTION_WINDOW_VERB!r} verb, so there is no promotion window to "
            "open a forward record against. A forward record's whole subject is "
            "the instant its signal went out of sample: feature 293 stamps it on "
            "the registry row and feature 300 reads it back, and this member "
            "writes no instant of its own rather than inventing one (feature "
            "332). The repair is the deployment's: a workspace with the "
            "promotion member scanned, whose module carries feature 300's "
            "window read"
        )
    try:
        return verb(
            node_id, forward_days=forward_days, database_url=database_url, env=env
        )
    except ForwardPromotionError:
        raise
    except Exception as refusal:
        # Feature 300's PromotionWindowError for a node nobody pre-registered,
        # a row whose deciding evaluation has not run, or a row unreadable as a
        # decision — and anything else the read raises.  Translated here rather
        # than caught by name because this module may not import the promotion
        # member's classes (a member never imports another, and the loader's
        # synthetic names would break the identity anyway): the refusal arrives
        # by message and leaves in this member's word, the same one-way
        # translation :mod:`dreaming.sweep` performs on a sibling's wrapper.
        raise ForwardPromotionError(
            f"{FORWARD_PROMOTION_ERROR_CODE}: node {node_id!r} has no promotion "
            f"instant to open a forward record against — the promotion member's "
            f"{PROMOTION_WINDOW_VERB!r} refused the read: {refusal}. A forward "
            "record carries the instant the signal went out of sample, which "
            "feature 293 stamped on the registry row and feature 300 reads back; "
            "until that instant exists there is nothing honest to write. "
            "Pre-register the promotion's criteria (feature 291), then record "
            "the decision once the deciding evaluation has run (feature 293), "
            "then open the forward record (feature 332) — a window opened at the "
            "clock this call happened to run at would measure a span that may "
            "begin inside the in-sample data the hypothesis was formed on"
        ) from refusal
