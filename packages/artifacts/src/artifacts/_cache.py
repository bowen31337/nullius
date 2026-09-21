"""The resident replay cache — the series cached, the marginal IR declined.

app_spec.xml, "Tree & Artifact Persistence", feature 176: *System declines
to cache marginal information ratio against canonical books, caching the
return series instead.*  docs/nullius-tech-architecture.md §9.3 states the
same sentence as an instruction and a refusal in one breath::

    **So do not cache marginal IR against canonical books. Cache the
    return series.**  Load each campaign's signal returns once as a
    single dense ``float32`` array of shape ``(nodes × T)`` and pin it
    in RAM

and closes the paragraph with the property this module is built to keep:
*"``ir_marginal`` then becomes array indexing plus a rank-1 update, with
no canonical-book cache anywhere."*

**Why the decline is the design, not a limitation.**  Three facts, each
one a reason a marginal-IR cache would be *wrong* rather than merely
expensive:

* *the key is unbounded.*  A return-series entry is keyed by a campaign
  — the one key the store owns — and §9.3 sizes its residence exactly:
  *500 nodes × 2000 periods × 4 B = 4 MB per campaign*.  A
  marginal-IR entry is keyed by ``(node, book)``, and the second term
  is a policy's *choice*: §10.1's ``replay(policy, tree, book, epoch)``
  receives the book as an argument, and every policy revision commits
  to a different one.  Nodes × books is the product of a growing set
  and an unbounded one — the ~160 GB-per-cycle blowup §9.3 opens with,
  moved out of I/O and into RAM.
* *a cached value is stale by construction.*  §9.2: *"Because it is
  stored in full, marginal contribution against any book can be
  recomputed at replay time, so the same node scores differently
  depending on the path a policy took to reach it."*  The book is an
  *argument* of ``ir_marginal``, not a dimension of the data; keying a
  cache by it would freeze one path's answer and serve it to every
  later policy that reaches the node another way — the exact accident
  that sentence rules out, and the reason §9.1 keeps ``ir_marginal``
  a column of one node's *own* evaluation while replay's copy is
  recomputed per (pick, book).
* *recomputation is what keeps replay deterministic.*  §9.3's replay
  path is deterministic *because* it recomputes from the stored
  series — §10.4 sizes it as "pure array arithmetic over cached
  Parquet".  A cache of derived scores would make replay a function of
  the cache's fill order instead of the data, and §9.2's closing
  condition ("while replay stays fully deterministic") would be gone.

**The decline is spoken, not silent.**  A design that merely *omitted*
the marginal-IR cache would let the first caller who wanted one build
it beside the member — silence is not a policy.  So the decline is a
named refusal at the two seams the ask can arrive by:
:func:`decline_marginal_ir` is the data-side spelling (feature 179's
:func:`artifacts.reject_duplicate` set the pattern — it needs no store,
because the verdict is a policy rather than a lookup), and
:meth:`ReturnSeriesCache.marginal_ir` is the object-side spelling, the
one a replay holding the cache reaches for first.  Both raise
:class:`~artifacts._errors.ArtifactMarginalIRDeclinedError` carrying
the :data:`DECLINED_MARGINAL_IR` code, and the refusal names the
*instead* in actionable terms: the resident series of the very
campaign the ask named, and §9.3's arithmetic over it.  The verdict
fires without touching the store — declining the ask is not looking
something up, and a campaign that was never persisted is declined just
the same as one that was.

**The instead is load-once, answer-resident.**  :class:`ReturnSeriesCache`
is the "caching the return series" half: bound to one
:class:`~artifacts.ArtifactStore`, it answers a campaign's
:class:`~artifacts.CampaignReturns` through feature 174's
:func:`~artifacts.load_campaign_returns` the *first* time it is asked,
and answers the same resident object every time after — one Parquet
sweep per ask-key per cache, then pure array indexing, which is
§9.3's whole answer to the replay bottleneck.  The residence is
observable and honest: a second ask does not re-read the store (the
array outlives the campaign's directory being deleted under it,
because it is *resident*), and a load that refuses leaves nothing
resident — the cache holds measurements, not attempts.  The cache is
per-process replay state, not a composed component and not a
correction of the store: the store stays the truth, so a cache built
after a re-persist answers the re-persisted campaign while one built
before keeps answering the array it loaded — both are correct, because
both answer a campaign that existed.  §9.3 pins arrays per replay and
§10.4 pins replays to a single core; the cache needs no lock for the
same reason the store's own listings take none.

**The key is the ask: one campaign, one horizon.**  The dense array is
one horizon deep (feature 174 pins :data:`~artifacts.
CAMPAIGN_LOAD_HORIZON`), so the cache keys by exactly what the caller
asked — ``(campaign_id, horizon)``, with the policy axis spelled
``None``.  A pinned horizon is its own resident axis even when it
equals the horizon the policy would resolve to: two asks, two resident
buffers, identical bytes — harmless *because* feature 174's loads are
deterministic ("two loads of one campaign answer the same array"),
which is the property that makes any spelling of the ask safe to
answer from residence.

**And structurally, there is no entry kind for anything else.**  The
cache's residence is a private mapping of campaign keys to
:class:`~artifacts.CampaignReturns` values: no public operation
accepts any other value type, no key spells a book, and the one ask
that would — the marginal information ratio against a canonical book —
is the named decline above.  That is §9.3's "no canonical-book cache
anywhere" made structural: the wrong entry cannot be cached by this
module even by accident, and the wrong ask cannot be answered by
silence.
"""

from __future__ import annotations

from typing import Any, NoReturn

from ._campaign import CampaignReturns, load_campaign_returns
from ._errors import ArtifactCacheError, ArtifactMarginalIRDeclinedError
from ._keys import validate_campaign_id, validate_node_id
from ._returns import _validated_horizon
from ._store import ArtifactStore

__all__ = [
    "DECLINED_MARGINAL_IR",
    "IR_MARGINAL",
    "RESIDENT_CACHE_POLICY",
    "ReturnSeriesCache",
    "decline_marginal_ir",
]

#: The metric the decline is about, in the one spelling the system uses
#: for it — §9.1's column (``ir_marginal REAL``), §6.1's step 9
#: ("orthogonalize vs. current book → ir_marginal") and feature 83's
#: scorer all write these eight characters.  Carried by name so the
#: refusal and the tests this feature owns cannot drift apart on which
#: quantity is declined.
IR_MARGINAL = "ir_marginal"

#: The role a declined ask's third term plays, for a message that names
#: which term of the declined key was which — the same service
#: :mod:`artifacts._dedup`'s ``CODE_HASH_ROLE`` does for its refusal.
BOOK_ROLE = "canonical book"

#: The error code feature 176's verdict carries, in the vocabulary the
#: feature's own sentence sets ("declines").  The message begins with
#: this token so the decline is greppable by the feature that defines
#: it — the convention :data:`artifacts.DUPLICATE_CODE_HASH` set, pinned
#: as a prefix rather than a substring so a log line cannot carry it by
#: accident.
DECLINED_MARGINAL_IR = "declined_marginal_ir"

#: The cache's content policy, spelled once the way
#: :data:`~artifacts.CAMPAIGN_LOAD_HORIZON` spells the load's horizon
#: policy: a sentence, not a type, because it is the *decision* the
#: feature's sentence pins and every seam that states it (the class's
#: docstrings, the refusal's message, the tests) quotes this one
#: spelling of it.
RESIDENT_CACHE_POLICY: str = (
    "cache the return series, never a marginal information ratio keyed "
    "against a canonical book"
)


# -- The decline --------------------------------------------------------------------


def decline_marginal_ir(
    campaign_id: Any, node_id: Any, book: Any
) -> NoReturn:
    """Decline the canonical-book marginal-IR ask — the verdict, spelled once.

    Feature 176's first half as one call: the ask to cache the marginal
    information ratio of one node against one canonical book is
    *declined*, in every spelling — stored, looked up, or warmed ahead
    of a replay — and the refusal is the named verdict
    :class:`~artifacts._errors.ArtifactMarginalIRDeclinedError` carrying
    the :data:`DECLINED_MARGINAL_IR` code, the §9.2 reason the entry
    would be stale by construction, and the *instead* this feature's
    own sentence pins: the resident return series of the very campaign
    the ask named, which §9.3's "array indexing plus a rank-1 update"
    turns the declined number into a recomputation.

    Needs no store and performs no I/O, because a decline is a policy
    rather than a lookup: the ask is refused for what it *is*, not for
    anything the store does or does not hold, so a campaign that was
    never persisted is declined exactly like one that was — the data
    the caller must reach instead is named in the refusal either way.

    The three terms are validated before the verdict is spoken, so a
    malformed ask is refused as malformed (a key that cannot address
    the layout is :class:`~artifacts.ArtifactKeyError`'s to refuse; a
    book that cannot be named is :class:`~artifacts.ArtifactCacheError`'s)
    and the caller fixes the ask rather than mistaking a typo for the
    policy.
    """
    campaign = validate_campaign_id(campaign_id)
    node = validate_node_id(node_id)
    named_book = _canonical_book_name(book)
    raise _marginal_ir_refusal(
        campaign_id=campaign, node_id=node, book=named_book
    )


def _canonical_book_name(book: Any) -> str:
    """The book a declined ask names, as nameable text — or the refusal.

    A canonical book is whatever a policy's committed pick amounts to;
    §10.1 hands one to every replay as an argument.  This seam asks only
    that it be *nameable* — non-empty text — because the decline is a
    verdict about the ask, not a lookup among known books: there is no
    registry of canonical books to consult on this side of the system
    (the book manager is §13.1's, the live side's), and a decline that
    depended on the book being registered would be a decline some
    spellings of the ask could sneak past.
    """
    if isinstance(book, str) and book.strip():
        return book.strip()
    raise ArtifactCacheError(
        f"a {BOOK_ROLE} a declined {IR_MARGINAL} ask is keyed against must "
        f"be a non-empty string — got {type(book).__name__} {book!r}; the "
        "book is the term the ask wanted to key its cache on, and a term "
        "that cannot be named is an ask malformed before it is declined — "
        "refused as malformed so the caller can fix the ask rather than "
        "mistake a typo for the policy"
    )


def _marginal_ir_refusal(
    *, campaign_id: str, node_id: str, book: str
) -> ArtifactMarginalIRDeclinedError:
    """The one verdict, spelled once for both seams that reach it.

    Names the ask's three terms, the §9.2 reason the design declines the
    entry, and the instead the feature's sentence pins — so a caller
    reading the refusal holds everything needed to do the right thing:
    which campaign's series to ask for, and that the declined number is
    a recomputation over it, never a recall.  The
    :data:`DECLINED_MARGINAL_IR` prefix is pinned as a prefix rather
    than a substring, so a log line cannot carry it by accident.
    """
    return ArtifactMarginalIRDeclinedError(
        f"{DECLINED_MARGINAL_IR}: the ask to cache the {IR_MARGINAL} of "
        f"node {node_id!r} of campaign {campaign_id!r} against the "
        f"{BOOK_ROLE} {book!r} is declined, in every spelling — stored, "
        "looked up, or warmed ahead of a replay — because §9.3's replay "
        "path holds 'no canonical-book cache anywhere'. The decline is "
        "the design, not a shortage: §9.2 — 'marginal contribution "
        "against any book can be recomputed at replay time, so the same "
        "node scores differently depending on the path a policy took to "
        "reach it' — makes the book an argument of the metric rather "
        "than a dimension of the data, so a cached value would freeze "
        "one path's answer and serve it to every later policy, and a "
        "(node, book) key would grow without the bound a resident "
        "series has (§9.3: 500 nodes × 2000 periods × 4 B = 4 MB per "
        "campaign). The instead is this feature's own second half: "
        "cache the return series — ask ReturnSeriesCache for the "
        f"resident series of campaign {campaign_id!r} "
        "(series(campaign_id)) and compute the marginal information "
        "ratio from it, §9.3's 'array indexing plus a rank-1 update' — "
        "recomputation is what keeps replay deterministic"
    )


# -- The instead --------------------------------------------------------------------


class ReturnSeriesCache:
    """§9.3's cache: each campaign's return series, resident, loaded once.

    The "caching the return series instead" half of feature 176.  Bound
    to one :class:`~artifacts.ArtifactStore` — the read side §1 grants
    the replay engine, reached only through feature 174's load, for
    which this cache adds no second decoder — it answers a campaign's
    :class:`~artifacts.CampaignReturns` the first time it is asked for
    and the *same resident object* every time after: one Parquet sweep
    per ``(campaign, horizon)`` key per cache, then array indexing,
    which is the whole of §9.3's answer to the replay bottleneck.

    The residence is the cache's own lifetime, deliberately: the store
    stays the truth, and §9.3 pins arrays per *replay* — a replay
    builds its own cache, a later replay builds a fresh one and reads
    the campaign as it was re-persisted since, and neither is ever
    handed a cache it did not build.  Nothing is evicted, because
    nothing arrives unasked: an entry appears exactly when a caller
    asks for its key, a load that refuses leaves nothing behind, and
    the bounded key (one campaign, one horizon) is the same bound
    §9.3's 4 MB-per-campaign sizing draws.

    The class holds no entry kind for anything but the return series —
    structurally, per the module docstring: there is no operation that
    accepts a derived metric, no key that spells a book, and the one
    ask shaped like one (``marginal_ir``) is the decline, answering the
    verdict :func:`decline_marginal_ir` spells.  §9.3's "no
    canonical-book cache anywhere" holds inside this object by
    construction.
    """

    def __init__(self, store: ArtifactStore) -> None:
        if not isinstance(store, ArtifactStore):
            raise ArtifactCacheError(
                "a resident return-series cache is bound to one "
                f"ArtifactStore — got {type(store).__name__} {store!r}; the "
                "cache loads campaigns through the store's read side and "
                "feature 174's load (there is no second decoder to trust), "
                "so a cache without that store is a cache nothing can be "
                "asked of"
            )
        self._store = store
        #: The residence: ``(campaign_id, horizon)`` → the loaded array.
        #: Private because the entry kind *is* the policy — a caller who
        #: could reach this mapping could put a derived metric in it,
        #: and feature 176 exists to make that unspellable.
        self._resident: dict[tuple[str, int | None], CampaignReturns] = {}

    @property
    def store(self) -> ArtifactStore:
        """The store this cache loads through — the truth it caches from."""
        return self._store

    def series(
        self, campaign_id: str, *, horizon: int | None = None
    ) -> CampaignReturns:
        """The campaign's resident return series — loaded once, answered resident.

        The first ask for ``(campaign_id, horizon)`` runs feature 174's
        :func:`~artifacts.load_campaign_returns` over the bound store —
        the only decoder this cache trusts, so every refusal of the
        load (a campaign holding no node directories, a node without
        its grid, panels from different sealed worlds, a horizon some
        panel covers no date of) refuses this ask unchanged, exactly as
        a direct load would answer it.  Every later ask for the same
        key answers the same resident object: no second Parquet sweep,
        no second decode, no re-validation — the array is the
        measurement §9.3 says to hold, and holding it is what this
        cache is for.

        ``horizon`` is feature 174's own knob with its own meaning:
        ``None`` (the default) is the policy axis
        :data:`~artifacts.CAMPAIGN_LOAD_HORIZON` resolves; an explicit
        horizon pins another axis, its own resident entry, answered
        under its own key.  A pinned horizon equal to the one the
        policy would resolve keeps its own resident buffer with
        identical bytes — two asks, two entries, one content, safe
        because feature 174's loads are deterministic.

        A load that refuses caches nothing: the ask raises the load's
        own error and the residence is exactly what it was, so the
        cache holds measurements, not attempts.
        """
        campaign = validate_campaign_id(campaign_id)
        pinned = None if horizon is None else _validated_horizon(horizon)
        key = (campaign, pinned)
        resident = self._resident.get(key)
        if resident is None:
            resident = load_campaign_returns(
                self._store, campaign, horizon=pinned
            )
            self._resident[key] = resident
        return resident

    def holds(
        self, campaign_id: str, *, horizon: int | None = None
    ) -> bool:
        """Whether the ``(campaign_id, horizon)`` axis is already resident.

        The question a caller holding a pin asks before loading another
        axis of a campaign already resident, answered from the
        residence alone: ``False`` touches no store and loads nothing,
        and a ``False`` that has become stale (the campaign was
        re-persisted since) is still the honest answer about *this*
        cache — the store is the truth, and this cache answers what it
        loaded, when it loaded it.
        """
        campaign = validate_campaign_id(campaign_id)
        pinned = None if horizon is None else _validated_horizon(horizon)
        return (campaign, pinned) in self._resident

    def resident_campaigns(self) -> tuple[str, ...]:
        """The campaigns this cache holds, sorted, each campaign once.

        The listing a replay's operator reads to see what is resident —
        the campaign axis of the residence, deduplicated across the
        horizon axes a caller may have pinned, in the store's own
        sorted order (:meth:`~artifacts.ArtifactStore.campaign_ids`'s
        discipline), because the order of a listing is part of what it
        is being used *for*: an operator comparing listings across
        replays compares content, never iteration order.
        """
        return tuple(sorted({campaign for campaign, _ in self._resident}))

    def marginal_ir(
        self, campaign_id: Any, node_id: Any, book: Any
    ) -> NoReturn:
        """The decline, at the object a replay holds — always the verdict.

        The ask this cache exists to refuse, spelled where a replay
        reaches first: the marginal information ratio of one node
        against one canonical book is neither cached nor served by this
        object, in any spelling, and the answer is
        :class:`~artifacts._errors.ArtifactMarginalIRDeclinedError` —
        the same verdict :func:`decline_marginal_ir` spells, message
        and code, so the two seams cannot drift apart on what is
        declined.  The refusal names this cache's own ``series`` seam
        as the instead, because a caller holding the cache is one call
        away from the data the declined number is recomputed from.
        """
        decline_marginal_ir(campaign_id, node_id, book)
