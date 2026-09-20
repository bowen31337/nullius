"""The Type-R root selection: which roots are null, drawn without replacement — feature 118.

app_spec.xml, "Null Oracle & Planted Nulls", feature 118: *System persists
Type-R null status drawn without replacement across roots, inherited by the
whole subtree.*  docs/nullius-tech-architecture.md §7.3 fixes the regime the
sentence belongs to::

    # Type-R (~70%): selection test. Null status inherited by the whole subtree.
    roots_null = rng.choice(roots, size=round(phi * W), replace=False)

and this module is that draw, the store that writes it down, and the
inheritance rule the sentence names.  It is the *first* of the two
null-assignment regimes §7.3 fixes: feature 119's Type-D keeps every root real
and flips a branch at a randomised depth (its own module says so in these
words), and this one keeps every *unselected* root real and turns a whole
root's subtree null.

**The sentence's three claims, and each of them is load-bearing.**

* *"drawn without replacement across roots"* — the draw picks ``round(φ·W)``
  **distinct** roots out of the campaign's ``W``, and every other root stays
  real.  *Without replacement* is not a stylistic detail: a draw *with*
  replacement may pick the same root twice, and each collision is a root that
  should have been null and stayed real — a world that plants fewer nulls than
  its fraction says, with the shortfall invisible, because the file that holds
  the labels holds only the bit.  §7.3's ``replace=False`` is therefore honoured
  literally, and :func:`draw_null_roots` is the one place the draw happens.
* *"persists"* — the drawn status is a fact about a campaign's world, fixed once
  and read back, never re-derived.  §12's determinism contract forbids a world
  whose nulls were re-drawn on each request, exactly as it forbids a null node
  whose permutation seed was re-drawn.  The draw is nevertheless *reproducible*
  — the seed is the campaign's own id — which is what lets an operator re-derive
  the world and check the sealed file against it.
* *"inherited by the whole subtree"* — a node is null **iff** its root is one of
  the drawn roots.  §7.3 states the inheritance immediately beside the draw
  ("Null status inherited by the whole subtree") and :meth:`TypeRSelection.
  null_status` is the rule: walk ``parent_id`` up to the root and read the
  root's recorded status.  The inheritance is a *rule*, not a stored entry per
  node, and the next section says why.

**Where the bit lands, and why it is the sidecar and nowhere else.**  Feature
109's §7.1 file is the one place in the entire system a node's null status is
written down — §1: *"There is no is_null column anywhere in the tree store. Not
hidden, not nulled out, not SELECT-excluded. Absent."* — and app_spec.xml gives
feature 110 the rule (*"System keeps is_null absent from the tree store
entirely, which rejects any proposed node column named is_null"*).  So this
feature's *persistence* half is not a new table and not a column on ``node``: it
is a write into the AES-GCM sidecar, one :class:`~nulloracle.assignment.
NullAssignment` per root, sealed by :class:`~nulloracle.sidecar.NullSidecar`.
That is the difference between this feature and its siblings — feature 117's φ,
feature 119's flip depth and feature 124's verdict are relational columns
precisely because they are *not* the bit — and it is why this store takes a
:class:`~nulloracle.sidecar.NullSidecar` beside its database URL: it needs the
tree (the roots, ``W`` and φ) *and* the one file allowed to hold the answer.

**The sidecar holds the roots, and the subtree is inherited — here is why.**
The obvious alternative is to materialise every node's status into the map, and
it is wrong for two reasons.  First, it is the same fact written ``|subtree|``
times: §7.1's map is a record of what was *decided*, and what was decided is
which roots are null.  Second, and decisively, the member's own read path
already states the contract — :meth:`~nulloracle.sidecar.NullSidecar.assignment`
answers ``None`` for a node the map does not hold, and the member's suite pins
that ``None`` as *"the honest answer for a real node's whole subtree in a Type-R
campaign (§7.3)"*.  A map that carried every node would make that sentence
false.  So the map carries one entry per **root** — the drawn ones with
``is_null`` true, the rest with ``is_null`` false — and a descendant's status is
its root's, found by the walk.  Recording the *unselected* roots as well is
deliberate: with every root present the file itself says *this campaign's
selection happened, and it chose these*, so an auditor can tell "drawn, and
nothing was null" from "never drawn" without holding φ or ``W``.

**φ is read, not taken as an argument.**  §7.3's ``size=round(phi * W)`` has
three inputs and two of them are facts about the campaign: ``W`` is feature
104's ``workspace_count`` and φ is the fraction feature 117 persisted on the
campaign row.  This module reads both from the row rather than accepting them —
which is the seam :mod:`nulloracle.phi` states from its own side (*"feature
118's Type-R draw and feature 119's Type-D flip depth read this fraction"*) —
because a caller-supplied φ or ``W`` that disagreed with the planner's would
plant a world the campaign was never designed with, and the disagreement would
be invisible: the draw would persist and resolve like any other.  The count is
therefore computed in exactly one place, :func:`null_root_count`, from the
stored fraction, with Python's ``round`` — half-to-even, the same convention
numpy's own rounding uses, so §7.3's ``round(phi * W)`` is reproduced rather
than reinterpreted.

**The seed is the campaign's, so a replayed world is the same world.**  The draw
comes from a :class:`random.Random` seeded by
:func:`~nulloracle.irprob.campaign_as_seed` — the one spelling this member has
for *a campaign id as a stable integer seed*, spelled beside the other draw that
feeds on it — and the roots are read in a stated order (``ORDER BY id``, then
sorted as canonical UUID text) so that the same campaign draws the same roots
however the storage engine returns its rows.  Feature 138's rule is the same
rule: explicit sorts before every reduction, because an iteration order that
varies with the engine is non-determinism wearing a stable-looking result.  Each
root's ``perm_seed`` — the parameter §7.1 seals *beside* the bit, and the one
feature 115's block permutation is reproduced from — is derived by
:func:`perm_seed_for` from the campaign and the root, so it too is a fact of the
campaign rather than of the call, and two roots get two seeds.

**Only the Type-R regime has a root selection.**  §7.3: *"Campaigns are
homogeneous in null type"*, and the two regimes keep their null-ness in
different places — a Type-R node's is the root selection this module draws, a
Type-D node's is feature 121's depth rule.  So ``campaign.campaign_type`` is
confirmed to be ``'Type-R'`` before a selection is drawn or read, and any other
type is refused with the type named.  The mirror of that refusal already exists:
:meth:`~nulloracle.resolution.TypeDOracle.resolve_request` refuses a ``'Type-R'``
campaign by name.  Feature 122's planning gate is what rejects a *plan* that
would mix the two; this module is the writer declining the regime it is not,
which is a different and narrower thing than the gate.

**The writer creates the file, never the campaign and never the node.**  A
campaign's roots are created by the discovery loop and its row by the planner
(feature 232's ``discovery`` plugin), both before any null is drawn — so a
campaign the table does not hold, and a tree with no roots, are refused by name
rather than invented.  The sidecar *file*, on the other hand, is exactly what
this store does create: a deployment whose first campaign draws its selection
has no ``sidecar.enc`` yet, and refusing to write the first one would make the
feature unusable.  That asymmetry is the deliberate one — a *writer* may start
from nothing, a *reader* may not: :meth:`TypeRSelection.load` and
:meth:`TypeRSelection.null_status` go through
:meth:`~nulloracle.sidecar.NullSidecar.open`, which raises for a missing file
rather than answering an empty map, because *"no file exists"* is a store
failure and must never read as *"no nulls were planted"*.

**Re-running refreshes, one campaign at a time.**  The grain is the campaign:
persisting a campaign's selection again replaces that campaign's roots' entries
and leaves every other campaign's entries in the file untouched — the same
whole-map merge :meth:`~nulloracle.sidecar.NullSidecar.write` performs, and the
same last-write-wins discipline feature 117's fraction, feature 119's flip depth
and feature 123's p-value state for their own grains.  A campaign re-planned with
a new ``W`` is the exact thing a refreshed selection records.  What is refused is
a *half*: the store reads the sealed file back inside the call and refuses a
selection whose written status and stored status disagree, because the bit the
whole FDR calibration rests on cannot be a value two processes would read
differently.

**Refusals, and each names what it is about.**  A malformed campaign or node id,
a stored fraction that is not a genuine probability, a stored ``W`` that is not a
positive count, a campaign the table does not hold, a campaign that is not
``'Type-R'``, a tree with no roots, a draw that would need more distinct roots
than the tree holds, a draw that would plant nothing at all, a node whose
ancestor chain cycles or dangles or crosses into another campaign, and a root
whose status was never recorded.  A malformed id is re-raised as
:class:`~nulloracle.errors.KsGuardError` rather than left as
:class:`~nulloracle.errors.SidecarError` — the taxonomy's split between a
store-contract failure and a sidecar-schema one, stated identically by feature
117's, feature 119's and feature 121's stores — while the *file's* own failures
(:class:`~nulloracle.errors.SidecarStoreError`,
:class:`~nulloracle.errors.SidecarAccessError`,
:class:`~nulloracle.errors.SidecarDecryptionError`) propagate unwrapped.  That
last part is deliberate and is the taxonomy's most important rule: a sidecar that
will not open must never be reported as a store-contract problem, because *"null
sidecar key lost → FDR history uninterpretable"* (§7) and *"this campaign was
never drawn"* are opposite findings about every score the system has recorded.

**Stdlib only, and import-cheap.**  ``hashlib``, ``os``, ``sqlite3``,
``dataclasses`` and ``urllib.parse`` at module scope, with ``random`` imported
where it is used, as feature 119's uniform and feature 120's shift are; the
sidecar's ``cryptography`` stays deferred to first use, so the factory's scan —
which imports this package to fire its ``@register`` — pays nothing for this
module.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
from collections.abc import Iterable, Mapping
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .assignment import NullAssignment, normalize_node_id
from .errors import KsGuardError
from .irprob import campaign_as_seed
from .sidecar import NullSidecar

__all__ = [
    "CAMPAIGN_TABLE",
    "CAMPAIGN_TYPE_COLUMN",
    "DATABASE_URL_ENV",
    "NODE_TABLE",
    "NULL_FRACTION_COLUMN",
    "TYPE_R_CAMPAIGN_TYPE",
    "WORKSPACE_COUNT_COLUMN",
    "RootSelection",
    "TypeRSelection",
    "draw_null_roots",
    "null_root_count",
    "perm_seed_for",
    "persist_type_r_selection",
]

#: The environment variable naming the relational store — the one spelling
#: every store in this workspace already uses (the ledger's, the guard's, the
#: verdict's, the fraction's, the flip depth's, the evaluator's five, the
#: repository-level conftest's), restated here so each store states its own
#: contract and none imports another's.
DATABASE_URL_ENV = "DATABASE_URL"

#: The table the campaign's φ and ``W`` are read from — feature 104's
#: ``campaign``, created by ``migrations/versions/0111_campaign_table.py``.
#: Spelled once here, and once in :mod:`nulloracle.phi`,
#: :mod:`nulloracle.flipdepth`, :mod:`nulloracle.irprob`,
#: :mod:`nulloracle.ksguard` and :mod:`nulloracle.verdict`, so the writers and
#: readers of the campaign row cannot drift apart on what it is called.
CAMPAIGN_TABLE = "campaign"

#: The campaign row's type — the column that decides which of §7.3's two
#: regimes a campaign belongs to.  Read, never written, here: the planner sets
#: it and this store only declines the regime it is not.
CAMPAIGN_TYPE_COLUMN = "campaign_type"

#: The campaign row's planted-null fraction — feature 117's column, and one of
#: the two inputs to §7.3's ``round(φ·W)``.  Read back rather than taken as an
#: argument: see the module docstring on why the draw's inputs are the
#: campaign's own facts.
NULL_FRACTION_COLUMN = "null_fraction"

#: The campaign row's workspace count — ``W``, the number of wells the campaign
#: was planned with, and the multiplicand §7.3's ``round(φ·W)`` applies the
#: fraction to.
WORKSPACE_COUNT_COLUMN = "workspace_count"

#: The table the campaign's roots are read from — feature 97's ``node``,
#: created by ``migrations/versions/0118_node_table.py``.  A campaign's roots
#: are the rows whose ``parent_id`` is ``NULL``: §7.3's ``roots`` list, and the
#: wells the draw chooses among.
NODE_TABLE = "node"

#: The campaign type this draw is for — §7.3's selection-test regime, the one
#: whose null status is a root selection inherited by the subtree.  The value
#: ``migrations/versions/0111_campaign_table.py`` documents and the campaign's
#: planner writes; spelled once here so this module's gate and its refusal share
#: one spelling of the regime they require — and so that feature 122's planning
#: gate has a name to compare against on both sides.
TYPE_R_CAMPAIGN_TYPE = "Type-R"


# -- Validation ------------------------------------------------------------------


def _validated_campaign_id(value: Any) -> str:
    """Validate a campaign id, returning it in canonical UUID text.

    Delegates to :func:`~nulloracle.assignment.normalize_node_id` — the one
    spelling this member has for *an id that joins the tree store's
    ``node.id``*, and ``campaign``'s ``id`` is the same kind of value — but
    re-raises its refusal as :class:`~nulloracle.errors.KsGuardError`.  The
    distinction is the taxonomy's: a malformed id handed to the *selection*
    store is a store-contract failure, not a sidecar-schema one, and a caller
    reading ``SidecarError`` out of a campaign's selection would look in the
    wrong module for the cause.  The fraction's, the flip depth's, the verdict's
    and this module's stores share the same id kind and the same error, so a
    campaign whose fraction is fixed, whose flip depths are drawn and whose
    Type-R selection is persisted are validated identically.
    """
    try:
        return normalize_node_id(value)
    except Exception as exc:  # noqa: BLE001 - re-raised by name below
        raise KsGuardError(f"campaign_id {value!r} is not a UUID: {exc}") from exc


def _validated_node_id(value: Any) -> str:
    """Validate a node id, returning it in canonical UUID text.

    The same delegation and the same re-raise as
    :func:`_validated_campaign_id`, with the field named as the node: the two
    ids join the same key and are refused the same way, and the message says
    which one the caller got wrong.
    """
    try:
        return normalize_node_id(value)
    except Exception as exc:  # noqa: BLE001 - re-raised by name below
        raise KsGuardError(f"node_id {value!r} is not a UUID: {exc}") from exc


def _validated_fraction(value: Any) -> float:
    """Refuse a stored φ that is not a genuine probability in ``(0, 1]``.

    φ is the fraction of a campaign's wells that are planted, so it is a real
    in ``(0, 1]``: feature 117's clip puts it in ``[0.15, 0.35]``, and this
    check is deliberately the *wider* one — it refuses a value that is not a
    fraction at all (a bool, a string, ``nan``, a negative, a value above one)
    rather than re-imposing feature 117's band.  The band is the fraction
    store's to apply at the write; a reader that re-imposed it would refuse a
    campaign an operator had deliberately re-banded, which is a policy change
    and not a corrupt row.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise KsGuardError(
            f"the campaign's {NULL_FRACTION_COLUMN} must be a real number, got "
            f"{type(value).__name__} ({value!r}); §7.3's Type-R draw plants "
            "round(φ·W) of a campaign's wells, and φ is the fraction feature "
            "117 persisted on the campaign row"
        )
    number = float(value)
    if not (number > 0.0 and number <= 1.0):
        raise KsGuardError(
            f"the campaign's {NULL_FRACTION_COLUMN} must lie in (0, 1], got "
            f"{number!r}; φ is the *fraction* of a campaign's wells that are "
            "planted, and a value outside (0, 1] plants a world no campaign "
            "was designed with"
        )
    return number


def _validated_workspace_count(value: Any) -> int:
    """Refuse a stored ``W`` that is not a genuine positive integer.

    ``W`` is the well count of the discovery tree (§7.3's ``2/W`` argument and
    feature 117's denominator), so ``W = 0`` is not a count, ``W < 0`` is not a
    count, and a fractional or truthy-looking ``W`` is not a count either.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise KsGuardError(
            f"the campaign's {WORKSPACE_COUNT_COLUMN} must be a positive "
            f"integer, got {type(value).__name__} ({value!r}); W is the well "
            "count of the discovery tree, a count and not a truthy-looking "
            "non-integer"
        )
    if value < 1:
        raise KsGuardError(
            f"the campaign's {WORKSPACE_COUNT_COLUMN} must be at least 1, got "
            f"{value!r}; §7.3's draw plants round(φ·W) roots and W is the "
            "number of wells the campaign was planned with"
        )
    return value


def _validated_roots(roots: Any) -> tuple[str, ...]:
    """Canonicalize a campaign's roots, sorted, refusing a list that is not one.

    §7.3 draws across a campaign's *wells*, so the collection must be non-empty,
    must hold ids that join the tree store's ``node.id``, and must hold each
    root **once**: "without replacement" is a statement about a set of distinct
    wells, and a list with a well in it twice is not one — a draw over it could
    return the same id twice while looking like a correct sample, which is
    exactly the duplicate §7.3's ``replace=False`` exists to forbid.

    Sorting is not cosmetic; see the module docstring — the draw must depend on
    the campaign and the root *set*, never on the order the storage engine
    returned the rows in.
    """
    if isinstance(roots, (str, bytes)) or not isinstance(roots, Iterable):
        raise KsGuardError(
            f"roots must be an iterable of node ids, got "
            f"{type(roots).__name__} ({roots!r}); §7.3 draws round(φ·W) of a "
            "campaign's wells without replacement, and a value that is not a "
            "collection of wells is not a list of roots to draw from"
        )
    canonical = tuple(_validated_node_id(root) for root in roots)
    if not canonical:
        raise KsGuardError(
            "the campaign's tree holds no roots; §7.3 draws "
            "round(φ·W) roots from the wells a campaign was planted with, and "
            "an empty tree is a tree the discovery loop has not created rather "
            "than a campaign that plants no nulls"
        )
    if len(set(canonical)) != len(canonical):
        raise KsGuardError(
            f"the campaign's roots hold a duplicate ({canonical!r}); §7.3's "
            "draw is across wells *without replacement*, and a well list with "
            "a well in it twice is not a set of distinct roots the draw could "
            "be without replacement over"
        )
    return tuple(sorted(canonical))


# -- Feature 118: the draw -------------------------------------------------------


def null_root_count(null_fraction: Any, *, workspace_count: Any) -> int:
    """§7.3's ``round(phi * W)``: how many distinct roots a Type-R draw turns null.

    The count in exactly one place, so the number the draw uses and the number a
    :class:`RootSelection` checks itself against cannot drift apart.  The
    rounding is Python's ``round`` — half-to-even on a tie, the same convention
    numpy's own rounding uses — so §7.3's ``size=round(phi * W)`` is
    *reproduced* rather than reinterpreted into a different tie rule.

    Refuses, and names what it refuses:

    * a ``null_fraction`` that is not a real fraction in ``(0, 1]`` — a bool, a
      string, a ``nan``, a negative, a value above one;
    * a ``workspace_count`` that is not a genuine positive integer;
    * a product that rounds below 1 — **a Type-R campaign that draws no null
      root measures nothing.**  §7.3's own floor argument is that *"a tree needs
      ≥2 null and ≥2 real roots to contribute to both sensitivity and
      specificity"*; a draw of zero nulls contributes no sensitivity at all, and
      the campaign would enter the pool reporting a Type-A rate over a world in
      which a Type-A error was impossible.
    """
    fraction = _validated_fraction(null_fraction)
    wells = _validated_workspace_count(workspace_count)
    count = round(fraction * wells)
    if count < 1:
        raise KsGuardError(
            f"φ = {fraction!r} over W = {wells!r} rounds to {count!r} null "
            "roots; §7.3's Type-R draw plants round(φ·W) of a campaign's wells, "
            "and a campaign that plants none contributes no sensitivity to the "
            "pool — it would report a Type-A rate over a world in which a "
            "Type-A error was impossible"
        )
    return count


def draw_null_roots(
    roots: Any,
    null_fraction: Any,
    *,
    workspace_count: Any,
    seed: Any,
) -> tuple[str, ...]:
    """§7.3's ``rng.choice(roots, size=round(phi * W), replace=False)``.

    The whole of feature 118's draw in one call, with no database and no file in
    the way: ``round(φ·W)`` **distinct** roots out of the campaign's wells, drawn
    from a generator seeded by the campaign, returned as canonical UUID text in
    sorted order.

    *Without replacement* is the load-bearing word of the sentence and is
    honoured literally — :meth:`random.Random.sample`, which cannot return a root
    twice.  A draw *with* replacement looks identical from the outside (a list of
    roots, each of them a root) and is wrong in the one way nothing downstream
    can see: every collision is a well that should have been null and stayed
    real, so the campaign plants fewer nulls than its fraction states and its
    Type-A count is measured against a smaller planted set than the world was
    designed with.

    The roots are canonicalized and **sorted** before the draw, so the result
    depends on the campaign and the root *set* and not on the order the storage
    engine returned the rows in — feature 138's rule (an explicit sort before
    every reduction) applied to the one reduction this feature performs.

    Refuses, and names what it refuses:

    * a ``roots`` collection that is empty, that repeats a root, or that holds
      an id that is not a UUID (:func:`_validated_roots`);
    * a fraction or workspace count :func:`null_root_count` refuses;
    * a count larger than the roots the tree holds — without replacement
      *cannot* draw more distinct roots than exist, and a campaign whose
      fraction asks for more wells than its tree has is a tree that is not the
      tree the campaign was planned with;
    * a ``seed`` that is not a genuine integer — the seed is the whole of the
      draw's reproducibility, and a seed the generator cannot be seeded with
      would make "the same campaign, the same world" unenforceable.

    Returns the **drawn** roots only.  The complement — the roots that stay real
    — is :meth:`TypeRSelection.persist`'s to derive, because §7.3's invariant is
    about both halves: every unselected root stays real.
    """
    wells = _validated_roots(roots)
    count = null_root_count(null_fraction, workspace_count=workspace_count)
    if count > len(wells):
        raise KsGuardError(
            f"φ = {null_fraction!r} over W = {workspace_count!r} asks for "
            f"{count!r} null roots but the tree holds {len(wells)}; §7.3's draw "
            "is across a campaign's wells *without replacement*, and a campaign "
            "whose fraction asks for more wells than its tree has is a tree "
            "that is not the tree the campaign was planned with"
        )
    return tuple(sorted(_seeded_sample(wells, count, seed)))


def _seeded_sample(wells: tuple[str, ...], count: int, seed: Any) -> list[str]:
    """:meth:`random.Random.sample` — ``count`` distinct wells from a seeded generator.

    Split out only so the refusal on a malformed seed sits beside the draw it
    belongs to; the sampling convention itself (``sample``, the
    without-replacement draw) is stated once, in :func:`draw_null_roots`.
    """
    import random

    if isinstance(seed, bool) or not isinstance(seed, int):
        raise KsGuardError(
            f"seed must be an integer, got {type(seed).__name__} ({seed!r}); "
            "§7.3's Type-R draw comes from a seeded generator and the seed is "
            "the whole of the draw's reproducibility, so a seed the generator "
            "cannot be seeded with would make a replayed campaign plant "
            "different nulls than it planted"
        )
    return random.Random(seed).sample(list(wells), count)


def perm_seed_for(campaign_id: Any, node_id: Any) -> int:
    """The permutation seed §7.1 seals beside ``node_id``'s null bit.

    §7.1's schema carries ``{is_null, perm_seed, block_days}``, and the word
    doing the work in feature 115's sentence is **stored**: *"System
    block-permutes forward returns for a null node using a stored permutation
    seed with a 20 day block length"*.  A permutation drawn fresh on every
    request would not be a world — the same campaign replayed would score
    differently against it — so the seed that generated a null node's permuted
    series is sealed *beside* the bit that says the node is null, and this is
    where it comes from: a sha256 over the campaign and the node, its first
    eight bytes read as a big-endian integer and shifted down one bit.

    Derived rather than drawn from the same stream as the selection, and that is
    deliberate.  A seed drawn *after* the sample would depend on how many roots
    the sample happened to visit, so a campaign replanned with a different ``W``
    would silently change the permutation of roots whose null status did not
    change at all — the world would move for a reason that has nothing to do
    with the root.  A per-``(campaign, node)`` derivation moves each root's
    permutation only when that root's identity or its campaign's does, and two
    roots always get two seeds.

    Always a non-negative integer below ``2**63``: the field is ``perm_seed:
    int`` in §7.1's schema, :func:`~nulloracle.assignment._validated_perm_seed`
    refuses a negative one, and 63 bits keeps the value inside the signed 64-bit
    range a relational store can hold if the seed is ever mirrored beside the
    bit.  The derivation is stable across processes and machines — sha256, not
    :func:`hash`, which is salted per process (feature 138 pins
    ``PYTHONHASHSEED`` for exactly this class of reason).

    A malformed campaign or node id is refused by name, as everywhere in this
    module: a seed derived from an id that cannot join the tree store's
    ``node.id`` names no root whose permutation it could reproduce.
    """
    campaign = _validated_campaign_id(campaign_id)
    node = _validated_node_id(node_id)
    digest = hashlib.sha256(f"{campaign}\x00{node}".encode()).digest()
    return int.from_bytes(digest[:8], "big") >> 1


@dataclass(frozen=True)
class RootSelection:
    """One campaign's Type-R selection: which roots are null, and the rest.

    Feature 118's answer to *"which wells of this campaign are the controls?"* —
    the campaign, the two disjoint root sets the draw produced, and the φ and
    ``W`` they were drawn from.  Frozen, so a selection that has been sealed can
    never be edited in place by a caller who kept a reference: the sidecar is a
    record of what was decided, and a mutable handle to it would be a mutable
    handle to a past decision — the same discipline
    :class:`~nulloracle.assignment.NullAssignment` and
    :class:`~nulloracle.resolution.TypeDResolution` state.

    Carrying ``real_roots`` rather than only the drawn ones is what makes the
    value *legible*: §7.3's invariant is a statement about both halves ("every
    unselected root stays real"), and a record that named only the nulls would
    leave an auditor to reconstruct the complement from φ and ``W`` — which is
    precisely the re-derivation this feature exists to avoid.

    Validated in :meth:`__post_init__`, including the coherence check that the
    two sets are disjoint, that together they are exactly the campaign's roots,
    and that the null set is the size :func:`null_root_count` says φ over ``W``
    gives.  That last one is the check that keeps a selection *checkable*: a
    record whose roots disagree with its own fraction cannot explain itself, and
    a world whose planted count disagrees with its stated fraction is a
    calibration number computed over a design that was never applied.
    """

    campaign_id: str
    null_roots: tuple[str, ...]
    real_roots: tuple[str, ...]
    null_fraction: float
    workspace_count: int

    def __post_init__(self) -> None:
        # ``object.__setattr__`` because the dataclass is frozen: the
        # canonicalization below is normalization, not mutation of the caller's
        # values, and it is the only write this object ever takes.
        object.__setattr__(self, "campaign_id", _validated_campaign_id(self.campaign_id))
        object.__setattr__(self, "null_roots", _sorted_ids(self.null_roots, "null_roots"))
        object.__setattr__(self, "real_roots", _sorted_ids(self.real_roots, "real_roots"))
        object.__setattr__(self, "null_fraction", _validated_fraction(self.null_fraction))
        object.__setattr__(
            self, "workspace_count", _validated_workspace_count(self.workspace_count)
        )
        if not self.null_roots:
            raise KsGuardError(
                "a Type-R selection must draw at least one null root; §7.3's "
                "draw plants round(φ·W) of a campaign's wells, and a campaign "
                "that plants none measures no sensitivity at all"
            )
        overlap = set(self.null_roots) & set(self.real_roots)
        if overlap:
            raise KsGuardError(
                f"the selection for campaign {self.campaign_id!r} lists "
                f"{sorted(overlap)!r} as both null and real; §7.3's draw is "
                "*without replacement* across a campaign's wells, so the drawn "
                "and the unselected roots are two disjoint sets of wells"
            )
        expected = null_root_count(self.null_fraction, workspace_count=self.workspace_count)
        if len(self.null_roots) != expected:
            raise KsGuardError(
                f"the selection for campaign {self.campaign_id!r} holds "
                f"{len(self.null_roots)} null roots but φ = {self.null_fraction!r} "
                f"over W = {self.workspace_count!r} is round(φ·W) = {expected}; "
                "a world whose planted count disagrees with its stated fraction "
                "is a calibration number computed over a design that was never "
                "applied"
            )

    @property
    def roots(self) -> tuple[str, ...]:
        """Every root the selection covers, null and real together, sorted."""
        return tuple(sorted(self.null_roots + self.real_roots))

    def is_null_root(self, node_id: Any) -> bool:
        """Whether ``node_id`` is one of the campaign's drawn null roots.

        A question about a *root*: a descendant is not in either set, and
        asking a descendant's status is :meth:`TypeRSelection.null_status`'s
        question — it walks to the root first.  A node in neither set is
        refused rather than answered ``False``, because ``False`` here means
        "drawn, and left real" and a node outside the selection is a node this
        campaign never planted.
        """
        node = _validated_node_id(node_id)
        if node in self.null_roots:
            return True
        if node in self.real_roots:
            return False
        raise KsGuardError(
            f"node {node!r} is not a root of campaign {self.campaign_id!r}; "
            "§7.3's Type-R selection covers the campaign's wells, and every "
            "other node inherits its root's status rather than being drawn"
        )

    def to_payload(self) -> dict[str, Any]:
        """The selection as a plain mapping, for a log line or an operator's report.

        The field names are the record's own, the same discipline
        :meth:`nulloracle.assignment.NullAssignment.to_payload` states: a
        rendered mapping and a structured log record name the same things the
        same way.
        """
        return {
            "campaign_id": self.campaign_id,
            "null_roots": list(self.null_roots),
            "real_roots": list(self.real_roots),
            "null_fraction": self.null_fraction,
            "workspace_count": self.workspace_count,
        }

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(campaign_id={self.campaign_id!r}, "
            f"{len(self.null_roots)} null of {len(self.roots)} roots, "
            f"φ={self.null_fraction!r})"
        )


def _sorted_ids(values: Any, field: str) -> tuple[str, ...]:
    """Canonicalize and sort a root set, refusing one that is not a set.

    The shared body of :class:`RootSelection`'s two root fields, so the two are
    validated identically and the refusal names which one was wrong.
    """
    if isinstance(values, (str, bytes)) or not isinstance(values, Iterable):
        raise KsGuardError(
            f"{field} must be an iterable of node ids, got "
            f"{type(values).__name__} ({values!r})"
        )
    canonical = tuple(_validated_node_id(value) for value in values)
    if len(set(canonical)) != len(canonical):
        raise KsGuardError(
            f"{field} holds a duplicate ({canonical!r}); §7.3's selection is a "
            "set of distinct wells"
        )
    return tuple(sorted(canonical))


# -- Feature 118: the store ------------------------------------------------------


class TypeRSelection:
    """The store that writes a Type-R campaign's root selection into the sidecar.

    Constructed with the database URL it reads the tree and the campaign row
    from, and the :class:`~nulloracle.sidecar.NullSidecar` it seals the drawn
    status into.  :meth:`persist` draws §7.3's selection for one campaign and
    writes it down; :meth:`load` reads one campaign's selection back; and
    :meth:`null_status` answers the sentence's inheritance rule for any node —
    walk to the root, read the root's status.

    Both halves are required, and that is the feature's shape rather than a
    convenience: the *draw* needs the tree (the roots, ``W``, φ) and the *bit*
    may only be written into §7.1's sealed file.  A store holding only the
    database could draw but not persist; one holding only the sidecar could
    persist but not draw.  The class resolves its database path lazily, so
    constructing one performs no I/O — composition-time work must not touch the
    disk, the contract every store in this workspace states — and the sidecar
    opens nothing until the first ``write()`` or ``open()``.

    The store holds no score and no series, and it holds no *cache* of the map
    it last sealed: §7.1's file is sealed and mode-``0600`` precisely so that
    reading it is the controlled operation, and a memo would move that operation
    to construction and then hold the plaintext labels for the process's
    lifetime — the same reasoning :class:`~nulloracle.sidecar.NullSidecar`
    states from its own side.
    """

    def __init__(self, database_url: str, sidecar: NullSidecar) -> None:
        if not isinstance(database_url, str) or not database_url.strip():
            raise KsGuardError(f"{DATABASE_URL_ENV} must be a non-empty database URL")
        if not isinstance(sidecar, NullSidecar):
            raise KsGuardError(
                f"the Type-R selection must be sealed into §7.1's sidecar, got "
                f"{type(sidecar).__name__} ({sidecar!r}); the null bit lives in "
                "the encrypted sidecar and in no other artifact — there is no "
                "is_null column anywhere in the tree store (feature 110)"
            )
        self._database_url = database_url.strip()
        self._sidecar = sidecar
        # Resolved on first use rather than at construction: building the store
        # is composition-time work and must not touch the disk.
        self._path: Path | None = None

    # -- Construction -------------------------------------------------------

    @classmethod
    def resolve(
        cls,
        env: Mapping[str, str] | None = None,
        *,
        material: bytes | None = None,
    ) -> TypeRSelection | None:
        """The selection store this environment names, or ``None`` when it names none.

        Both halves must be resolvable: a database URL (empty or
        whitespace-only counts as unset) *and* a
        :class:`~nulloracle.sidecar.NullSidecar`, which
        :meth:`~nulloracle.sidecar.NullSidecar.resolve` answers ``None`` for
        when nothing names a location or a key.  Absent is not an error: it is a
        deployment without a relational store or without a sidecar, which
        composes no selection component — a discoverable state, not an
        exception — while the campaign loop that must plant §7.3's Type-R world
        is the caller that must not find itself in it.

        ``material`` is threaded through to the sidecar's own resolution for a
        process that already holds the key from its backend, the same seam
        :meth:`~nulloracle.sidecar.NullSidecar.resolve` offers.

        **This method never raises.**  The factory builds every registered
        component on every :func:`~app.module_loader.create_app` call, so a
        builder that raised would take composition down for every unrelated
        feature in the workspace — the stance every store in this member states.
        """
        source = os.environ if env is None else env
        raw = source.get(DATABASE_URL_ENV, "").strip()
        if not raw:
            return None
        sidecar = NullSidecar.resolve(source, material=material)
        if sidecar is None:
            return None
        return cls(raw, sidecar)

    @property
    def database_url(self) -> str:
        """The database URL this store reads from."""
        return self._database_url

    @property
    def sidecar(self) -> NullSidecar:
        """The sidecar this store seals the drawn status into."""
        return self._sidecar

    @property
    def path(self) -> Path:
        """The SQLite file backing this store, resolved on first use.

        Nothing is created at construction — the URL is translated (and a URL
        this member cannot speak is refused by name) the first time an operation
        needs it.
        """
        if self._path is None:
            self._path = _sqlite_path(self._database_url)
        return self._path

    def _connect(self) -> sqlite3.Connection:
        """Open the database and ensure the node and campaign tables exist, idempotently.

        ``CREATE TABLE IF NOT EXISTS`` on the node table (feature 97's five
        structural columns, as ``migrations/versions/0118_node_table.py`` spells
        them) and on the campaign table (feature 104's, as ``0111`` spells it) —
        the contract every store in this workspace states: a fresh database and
        a migration-created one take the same path, so no migration step is
        needed here and running the migration over a database this store created
        changes nothing.

        No column is added, and in particular no ``is_null`` column ever is:
        feature 110 keeps the bit out of the tree store entirely, and this
        store's storage half is the sealed file rather than a column.  The
        tables are opened because the *roots* and the campaign's φ and ``W`` are
        read from them.
        """
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        with connection:
            connection.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS {NODE_TABLE} (
                    id                 UUID NOT NULL PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', abs(random()) % 4 + 1, 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
                    parent_id          UUID,
                    campaign_id        UUID NOT NULL,
                    theme_root         TEXT NOT NULL,
                    depth              INT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS {CAMPAIGN_TABLE} (
                    id                 UUID NOT NULL PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', abs(random()) % 4 + 1, 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
                    campaign_type      TEXT NOT NULL,
                    workspace_count    INT NOT NULL,
                    null_fraction      REAL NOT NULL,
                    calibration_status TEXT NOT NULL DEFAULT 'ok',
                    ks_pvalue          REAL,
                    created_at         TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                );
                """
            )
        return connection

    # -- Feature 118: the write ---------------------------------------------

    def persist(self, campaign_id: Any) -> RootSelection:
        """Draw §7.3's Type-R selection for ``campaign_id`` and persist it.

        The whole of feature 118 in one call: the campaign is confirmed to exist
        and to be a ``'Type-R'`` campaign, its φ and ``W`` are read from its own
        row, its roots are read from the tree, ``round(φ·W)`` distinct roots are
        drawn without replacement from a generator seeded by the campaign, and
        **every** root's status is sealed into §7.1's sidecar — ``True`` for the
        drawn ones, ``False`` for the rest — with each root's ``perm_seed``
        derived from the campaign and the root.

        Every root is written, not only the null ones, for the reason the module
        docstring gives: with all of them present the file itself records that
        the selection *happened*, so *"drawn, and nothing was null"* stays
        distinguishable from *"never drawn"* — a distinction the whole member's
        error taxonomy is built around.

        Other campaigns' entries are preserved.  §7.1's file holds one map for
        the deployment, so a campaign's write merges its own roots into whatever
        the file already holds and leaves every entry whose node is not one of
        this campaign's roots exactly as it was.

        Refuses, in this order, and each refusal names what it is about:

        1. a malformed ``campaign_id`` (:class:`~nulloracle.errors.KsGuardError`);
        2. a campaign the table does not hold
           (:class:`~nulloracle.errors.KsGuardError`) — the selection is a fact
           about a campaign, and drawing one for a row this store invented would
           plant a world no planner designed;
        3. a campaign that is not ``'Type-R'``
           (:class:`~nulloracle.errors.KsGuardError`, with the type named) — §7.3
           keeps the two regimes' null-ness in different places, and drawing a
           root selection for a Type-D campaign would write a bit that
           contradicts the depth rule feature 121 resolves the same tree with;
        4. a stored φ or ``W`` that is not a genuine fraction or count, or a
           draw of no null roots at all (see :func:`null_root_count`);
        5. a tree with no roots, or one that holds fewer roots than the fraction
           asks for (see :func:`draw_null_roots`);
        6. a write that could not be completed, or a sealed file that does not
           read back as what was written
           (:class:`~nulloracle.errors.KsGuardError`).

        A :class:`~nulloracle.errors.SidecarStoreError`,
        :class:`~nulloracle.errors.SidecarAccessError` or
        :class:`~nulloracle.errors.SidecarDecryptionError` from the file is left
        to propagate unwrapped — the file's failures are the file's, and a
        caller must never read *"the sidecar would not open"* as *"this campaign
        was never drawn."*

        Re-running refreshes: the grain is the campaign, so a campaign replanned
        with a new ``W`` gets a new draw and the file's older entries for its
        roots are replaced, while a different campaign's entries are untouched.
        """
        campaign = _validated_campaign_id(campaign_id)
        with closing(self._connect()) as connection:
            campaign_type, fraction, wells = self._read_campaign(connection, campaign)
            roots = self._read_roots(connection, campaign)
        self._require_type_r(campaign, campaign_type)
        drawn = draw_null_roots(
            roots,
            fraction,
            workspace_count=wells,
            seed=campaign_as_seed(campaign),
        )
        planted = set(drawn)
        selection = RootSelection(
            campaign_id=campaign,
            null_roots=drawn,
            real_roots=tuple(root for root in roots if root not in planted),
            null_fraction=fraction,
            workspace_count=wells,
        )
        written = {
            root: NullAssignment(
                node_id=root,
                is_null=root in planted,
                perm_seed=perm_seed_for(campaign, root),
            )
            for root in selection.roots
        }
        self._sidecar.write(self._merged(written))
        self._verify(selection, written)
        return selection

    def load(self, campaign_id: Any) -> RootSelection | None:
        """One campaign's persisted selection, or ``None`` when it holds none.

        ``None`` means *this campaign's roots are not in the sidecar* — the
        selection was never persisted — which is the honest answer for a
        campaign whose wells the file does not mention.  It does **not** mean
        the read failed: a missing sidecar file raises
        :class:`~nulloracle.errors.SidecarStoreError`, an unreadable one raises
        :class:`~nulloracle.errors.SidecarAccessError`, and one that will not
        authenticate raises
        :class:`~nulloracle.errors.SidecarDecryptionError`.  A caller can
        therefore never mistake a broken sidecar for an unplanted world — §7's
        failure table is why that distinction is the taxonomy's most important
        rule.

        The ``real_roots`` are the campaign's roots the file records as *not*
        null, and the φ and ``W`` come from the campaign row rather than from
        the file: the file holds the bit and its perm parameters, which is
        exactly what §7.1's schema spells, and the fraction is the campaign's
        own column (feature 117's).

        Refuses by name a campaign the table does not hold, a campaign that is
        not ``'Type-R'``, a tree with no roots, a root whose entry the file
        holds but whose status is not a genuine bool — an entry the file holds
        for one of this campaign's roots but not for another is a *half*, and is
        refused (:class:`~nulloracle.errors.KsGuardError`) rather than reported
        as a selection nobody drew.
        """
        campaign = _validated_campaign_id(campaign_id)
        with closing(self._connect()) as connection:
            campaign_type, fraction, wells = self._read_campaign(connection, campaign)
            roots = self._read_roots(connection, campaign)
        self._require_type_r(campaign, campaign_type)
        assignments = self._sidecar.open()
        held = {
            root: assignments[root] for root in roots if root in assignments
        }
        if not held:
            return None
        missing = [root for root in roots if root not in held]
        if missing:
            raise KsGuardError(
                f"the sidecar holds entries for {len(held)} of campaign "
                f"{campaign!r}'s {len(roots)} roots; §7.3's selection is "
                "persisted as one entry per well, and a file holding some of a "
                f"campaign's roots and not others is a half — the roots {missing!r} "
                "are recorded nowhere, so the world they belong to cannot be read "
                "back as one"
            )
        null_roots = tuple(
            root for root in roots if _validated_is_null(held[root].is_null, root)
        )
        planted = set(null_roots)
        return RootSelection(
            campaign_id=campaign,
            null_roots=null_roots,
            real_roots=tuple(root for root in roots if root not in planted),
            null_fraction=fraction,
            workspace_count=wells,
        )

    # -- Feature 118: the inheritance --------------------------------------

    def null_status(self, node_id: Any) -> bool:
        """Whether ``node_id`` is null — its root's status, inherited whole.

        The sentence's third claim as one call: *"inherited by the whole
        subtree."*  The node is confirmed to exist and to belong to a
        ``'Type-R'`` campaign, ``parent_id`` is followed up to the root, and the
        root's status is read from §7.1's sidecar.  A descendant of a null root
        is null; a descendant of any other root is real; and the two never mix,
        because the status is a property of the *root* and the walk is the whole
        of the derivation.

        The walk refuses, by name, a node whose ancestor chain **revisits** a
        node (a cycle — the walk would not terminate) and a node whose
        ``parent_id`` names a node the table does not hold (a dangling edge — the
        walk would end at a node that was never placed).  Both are corrupt-tree
        refusals rather than statuses: a branch whose chain cannot be walked to
        its root is a branch whose root cannot be found, not a real one.  The
        walk also refuses a chain that crosses into another campaign: §7.3 scopes
        a tree to one campaign, and a node whose ancestor belongs elsewhere is a
        node whose root the campaign never planted.

        A root whose status the sidecar does not record is refused rather than
        answered — the opposite of ``None``'s meaning in
        :meth:`~nulloracle.sidecar.NullSidecar.assignment`, and deliberately so:
        §7.3 records *every* root, so a root missing from the file is a campaign
        whose selection was never persisted, and serving ``False`` there would
        report a real world for a campaign that planted nulls.

        The sidecar's own failures propagate unwrapped, as in :meth:`load`: a
        file that will not open never reads as a status.
        """
        node = _validated_node_id(node_id)
        with closing(self._connect()) as connection:
            campaign, root = self._walk_to_root(connection, node)
            campaign_type, _, _ = self._read_campaign(connection, campaign)
        self._require_type_r(campaign, campaign_type)
        assignment = self._sidecar.assignment(root)
        if assignment is None:
            raise KsGuardError(
                f"root {root!r} of campaign {campaign!r} is recorded nowhere in "
                f"the sidecar, so node {node!r}'s status cannot be inherited; "
                "§7.3's Type-R selection is persisted as one entry per root "
                "*before* the tree is scored, and a root the file does not hold "
                "is a campaign whose nulls were never planted"
            )
        return _validated_is_null(assignment.is_null, root)

    # -- The tree -----------------------------------------------------------

    def _read_campaign(
        self, connection: sqlite3.Connection, campaign: str
    ) -> tuple[Any, float, int]:
        """The campaign row's type, φ and ``W``, read once.

        Three of the four facts the draw needs, and every one of them read back
        from the campaign's own row rather than accepted as an argument — see
        the module docstring on why a caller-supplied φ or ``W`` would plant a
        world the campaign was never designed with.  The row is created by the
        planner *before any node is expanded*, so a campaign the table does not
        hold is refused by name: a store that inserted the missing campaign would
        be inventing the row the type and the workspace count belong on.
        """
        cursor = connection.execute(
            f"SELECT {CAMPAIGN_TYPE_COLUMN}, {NULL_FRACTION_COLUMN}, "
            f"{WORKSPACE_COUNT_COLUMN} FROM {CAMPAIGN_TABLE} WHERE id = ?",
            (campaign,),
        )
        try:
            row = cursor.fetchone()
        finally:
            cursor.close()
        if row is None:
            raise KsGuardError(
                f"the campaign table holds no row for {campaign!r}; §7.3's "
                "Type-R selection is fixed *per campaign*, so a selection that "
                "cannot be joined to the campaign it was planned for is refused "
                "rather than drawn onto a row this store would have to invent — "
                "the campaign is created by its planner, before any node is "
                "expanded"
            )
        return row[0], _validated_fraction(row[1]), _validated_workspace_count(row[2])

    def _read_roots(
        self, connection: sqlite3.Connection, campaign: str
    ) -> tuple[str, ...]:
        """The campaign's roots — §7.3's ``roots`` list, in a stated order.

        A root is a node whose ``parent_id`` is ``NULL``, which is the edge
        ``migrations/versions/0118_node_table.py`` describes: *"A root node
        carries ``NULL``; every other node names its parent."*  ``ORDER BY id``
        is stated rather than left to the engine so the same campaign reads its
        wells in the same order everywhere; :func:`draw_null_roots` sorts them
        again as canonical UUID text, because SQLite's text ordering of the
        same ids is not the one the draw is pinned to.
        """
        cursor = connection.execute(
            f"SELECT id FROM {NODE_TABLE} WHERE campaign_id = ? AND parent_id IS NULL "
            "ORDER BY id",
            (campaign,),
        )
        try:
            rows = cursor.fetchall()
        finally:
            cursor.close()
        return _validated_roots([row[0] for row in rows])

    def _walk_to_root(
        self, connection: sqlite3.Connection, node: str
    ) -> tuple[str, str]:
        """Walk ``node``'s ancestor chain to its root; return ``(campaign, root)``.

        Follows ``parent_id`` upward from the node itself, refusing a chain that
        revisits a node, a ``parent_id`` that is not a UUID, a ``parent_id``
        naming a node the table does not hold, a node naming no campaign, and an
        ancestor that belongs to a different campaign.  Each refusal is by name
        and each is a corrupt-tree fact rather than a status: a chain that
        cannot be walked to its root is a chain whose root cannot be found.

        The walk is bounded in practice by the tree's depth and, on a cycle, by
        the visited set — which is why the cycle check is a set membership test
        rather than a depth cap: a depth cap would silently truncate a
        legitimately deep tree, and a tree that deep is not this function's
        business to refuse.
        """
        current = node
        campaign: str | None = None
        visited: set[str] = set()
        while True:
            if current in visited:
                raise KsGuardError(
                    f"node {node!r}'s ancestor chain revisits {current!r}; §7.3's "
                    "Type-R status is inherited from a node's root, and a chain "
                    "that cycles has no root for a status to be inherited from"
                )
            visited.add(current)
            cursor = connection.execute(
                f"SELECT parent_id, campaign_id FROM {NODE_TABLE} WHERE id = ?",
                (current,),
            )
            try:
                row = cursor.fetchone()
            finally:
                cursor.close()
            if row is None:
                raise KsGuardError(
                    f"the node table holds no row for {current!r}"
                    + (
                        ""
                        if current == node
                        else f", an ancestor of node {node!r}"
                    )
                    + "; §7.3's Type-R status is inherited from a node's root, "
                    "and a chain that dangles at a node the discovery loop "
                    "never placed has no root to inherit from"
                )
            parent, campaign_value = row
            if campaign_value is None:
                raise KsGuardError(
                    f"node {current!r} names no campaign; §7.3 scopes a "
                    "discovery tree to one campaign, and a node belonging to "
                    "none has no campaign whose selection it inherits"
                )
            here = _validated_campaign_id(campaign_value)
            if campaign is None:
                campaign = here
            elif here != campaign:
                raise KsGuardError(
                    f"node {node!r}'s ancestor chain crosses from campaign "
                    f"{campaign!r} into {here!r} at {current!r}; §7.3 scopes a "
                    "discovery tree to one campaign, and a node whose ancestor "
                    "belongs elsewhere is a node whose root this campaign never "
                    "planted"
                )
            if parent is None:
                return campaign, _validated_node_id(current)
            current = _validated_node_id(parent)

    def _require_type_r(self, campaign: str, campaign_type: Any) -> None:
        """Refuse a campaign that is not §7.3's selection-test regime, by name.

        Only the Type-R regime has a root selection: a Type-D campaign keeps
        *every root real* and flips a branch at a randomised depth, which is
        feature 119's fact living on the flip-depth column.  The refusal names
        the type the campaign actually is, so a caller that mixed the two learns
        which regime it reached for — the same discipline
        :meth:`~nulloracle.resolution.TypeDOracle.resolve_request` applies from
        the other side, refusing a ``'Type-R'`` campaign by name.  Feature 122's
        planning gate is what rejects a plan that would *mix* the two within one
        tree; this is the narrower refusal of a writer declining the regime it is
        not.
        """
        if campaign_type != TYPE_R_CAMPAIGN_TYPE:
            raise KsGuardError(
                f"campaign {campaign!r} is a {campaign_type!r} campaign; §7.3's "
                f"Type-R root selection is drawn for a "
                f"{TYPE_R_CAMPAIGN_TYPE!r} campaign, where the null status is a "
                "root selection inherited by the whole subtree — a Type-D "
                "campaign keeps every root real and flips a branch at its "
                "drawn flip depth instead (feature 119), and campaigns are "
                "homogeneous in null type"
            )

    # -- The sidecar --------------------------------------------------------

    def _merged(
        self, written: Mapping[str, NullAssignment]
    ) -> dict[str, NullAssignment]:
        """This campaign's entries merged into whatever the sidecar already holds.

        §7.1's file holds one map for the deployment, so a campaign's write must
        not drop every other campaign's roots.  A sidecar that has never been
        written is *not* an error here — this is the writer, and a deployment's
        first campaign has no ``sidecar.enc`` yet; the reader's side of that
        asymmetry is :meth:`~nulloracle.sidecar.NullSidecar.open`, which refuses
        a missing file.  Deriving §7.1's default block length rather than
        copying it is deliberate: :class:`~nulloracle.assignment.NullAssignment`
        applies :data:`~nulloracle.assignment.DEFAULT_BLOCK_DAYS`, and §7.4's
        operator turns that knob in one place.
        """
        existing: dict[str, NullAssignment] = (
            self._sidecar.open() if self._sidecar.exists() else {}
        )
        merged = {
            node: assignment
            for node, assignment in existing.items()
            if node not in written
        }
        merged.update(written)
        return merged

    def _verify(
        self, selection: RootSelection, written: Mapping[str, NullAssignment]
    ) -> None:
        """Read the sealed file back and refuse a selection that was written half.

        The bit the whole FDR calibration rests on cannot be a value two
        processes would read differently, so the status this store just sealed
        is read back rather than trusted — the same read-back-rather-than-trust
        discipline feature 117's fraction, feature 119's flip depth and feature
        121's resolution apply to the values they write.  An entry that came
        back missing, or with a different ``is_null`` or a different
        ``perm_seed``, is a half, and is refused with the root named.
        """
        sealed = self._sidecar.open()
        for root, expected in written.items():
            found = sealed.get(root)
            if found is None:
                raise KsGuardError(
                    f"root {root!r} is missing from the sidecar immediately "
                    f"after campaign {selection.campaign_id!r}'s selection was "
                    "written to it; §7.3's selection is persisted as one entry "
                    "per well, and a well that cannot be re-read is a well "
                    "whose status is unverifiable"
                )
            if found.is_null != expected.is_null or found.perm_seed != expected.perm_seed:
                raise KsGuardError(
                    f"root {root!r} was written half: the sealed entry holds "
                    f"is_null={found.is_null!r}, perm_seed={found.perm_seed!r} "
                    f"and the selection wrote is_null={expected.is_null!r}, "
                    f"perm_seed={expected.perm_seed!r}; §7.3's Type-R status and "
                    "the seed feature 115 permutes from are sealed together, "
                    "and a pair whose written value and stored value disagree "
                    "is not a world"
                )


def _validated_is_null(value: Any, root: str) -> bool:
    """Refuse a sealed status that is not a genuine bool, naming its root.

    :class:`~nulloracle.assignment.NullAssignment` already refuses a non-bool at
    construction and at the read, so this is belt-and-braces on the read path —
    and it is deliberately here rather than a bare ``bool(...)``, because
    coercing is the one thing §7.1's schema forbids: the string ``"false"`` is
    truthy, and a coercion would plant a real root as a null one with nothing
    downstream looking wrong.
    """
    if not isinstance(value, bool):
        raise KsGuardError(
            f"the sidecar's entry for root {root!r} holds is_null="
            f"{value!r} ({type(value).__name__}); §7.1's schema fixes the null "
            "bit as a genuine bool, and a value that merely looks true or "
            "false is refused rather than coerced into a status"
        )
    return value


def _sqlite_path(database_url: str) -> Path:
    """Translate a ``sqlite:///`` URL into a filesystem path.

    The SQLAlchemy convention the workspace's ``DATABASE_URL`` already uses,
    restated here rather than imported so each store states its own contract.  A
    non-SQLite scheme is refused loudly — the Postgres store arrives with the
    migration member — and a pathless (in-memory) URL is refused too: an
    in-memory database dies with the connection that opened it, and a campaign's
    tree must outlive the draw that read it.
    """
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise KsGuardError(
            f"unsupported {DATABASE_URL_ENV} scheme {parsed.scheme!r}: this "
            "store speaks sqlite:/// (the spec's single-machine allowance); "
            f"point {DATABASE_URL_ENV} at a sqlite database"
        )
    if parsed.netloc not in ("", "localhost"):
        raise KsGuardError(
            f"sqlite {DATABASE_URL_ENV} must not carry a host, got "
            f"{parsed.netloc!r}"
        )
    path = unquote(parsed.path).removeprefix("/")
    if not path or path == ":memory:":
        raise KsGuardError(
            f"sqlite {DATABASE_URL_ENV} carries no database path: an in-memory "
            "database would die with the connection that opened it, and a "
            "campaign's tree must outlive the selection drawn from it"
        )
    return Path(path)


def persist_type_r_selection(
    campaign_id: Any,
    sidecar: NullSidecar,
    *,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
) -> RootSelection:
    """Draw §7.3's Type-R selection for ``campaign_id`` and persist it — the module-level spelling.

    Feature 118's sentence as one call: the campaign in, which of its roots are
    null out, sealed into §7.1's sidecar and inherited by every descendant.  The
    store is resolved from ``database_url``, else from ``DATABASE_URL``; a
    deployment that names neither is refused *by name* rather than silently
    doing nothing, because a selection that quietly skipped its write would
    leave a campaign looking undrawn while the campaign loop believed it had
    planted §7.3's world — which is the failure mode this whole feature exists to
    rule out.

    The sidecar is an argument rather than environment-resolved, because the
    *writer* of a campaign's world is the process that holds the key: an
    operator script and a scorer are different processes (§2's trust table gives
    the sidecar its own IAM role), and asking the environment for a key here
    would let a process that may not hold one compose a store that seals
    anything.  A caller that wants the environment's sidecar asks
    :meth:`TypeRSelection.resolve`, or
    :meth:`~nulloracle.sidecar.NullSidecar.resolve` directly.

    A :class:`~nulloracle.errors.KsGuardError` from the store is left to
    propagate unwrapped; see the taxonomy for why *"the selection could not be
    written down"* is a store-contract failure and not a computation one — and
    why the *file's* failures are neither, and are never translated.
    """
    source = os.environ if env is None else env
    url = (
        database_url
        if database_url is not None
        else source.get(DATABASE_URL_ENV, "").strip()
    )
    if not url:
        raise KsGuardError(
            "persist_type_r_selection draws a campaign's Type-R root selection "
            f"and nothing names a store: {DATABASE_URL_ENV} is unset (and no "
            "database_url was supplied), so §7.3's selection could not be read "
            "from the tree or written down. A campaign's null status is a fact "
            "that must actually land in §7.1's sidecar — a selection that "
            "silently went nowhere would leave a campaign looking undrawn while "
            "its loop believed it had planted the world"
        )
    return TypeRSelection(url, sidecar).persist(campaign_id)
