"""Feature 315: isolated margin per book, judged before anything is placed.

app_spec.xml, "Order Routing & Venue Filters", feature 315: *System uses
isolated margin per book, which rejects a cross-margin configuration that
would merge independent positions.*  The clause after the comma is the verb,
and this module is it: a **verdict over a configuration the caller already
holds**, refusing the one arrangement the sentence names.

**Why the mode is refused rather than defaulted.**  ``docs/nullius-tech-
architecture.md`` §13.2 and ``docs/alpha-engine-prd.md`` C9 both state the
rule and the reason in one line each: *"Isolated margin per book. Cross
margin converts N independent positions into one position with N legs, and a
single leg's liquidation cascades into the rest."*  The deployment runs more
than one book (§C9's books, and feature 316's ``book_id`` term exists because
"two books holding the same symbol at the same instant are two orders"), and
the entire point of running them as independent books is that their positions
are independent.  Cross margin deletes that: the account's whole balance
stands behind every leg, so a book that is right is liquidated to pay for a
book that is wrong, and the loss a caller sized against the book's own
volatility is bounded by something the book does not own.  Nothing downstream
can detect this — the order path builds exactly the same orders either way,
against the same filters, under the same keys — so the gate has to be *here*,
before the first order, where the configuration is still named.

**A configuration, not an order — and therefore not a per-order check that
could be skipped.**  §13.2 places this line among the execution engine's
constant rules, beside *"Never hardcoded"* and *"Post-only by default"*, and
each of those is a property of the *deployment* rather than of one order.
Feature 314's passive/aggressive choice and feature 321's live-authority flag
are per-order; this is not.  So the verb takes the book that is being
configured and the account it will settle against, and answers a value — a
:class:`BookMargin` — that the order path holds and the configuration records.

**Two facts are judged, and each has its own fault.**  The sentence names one
mode and the merged thing it refuses.  The *mode* is the vocabulary
:data:`MARGIN_MODES` closes: ``isolated`` — the mode the sentence requires and
the only value that trades — and ``cross``.  Anything else is not a mode this
system can be configured with, and is refused naming the value rather than
mapped onto one of the two, because a mode this module guessed at would be a
margin arrangement nobody stated.  The *account* is the thing that merges: two
books pointing at one account are one position with N legs whatever mode label
each book carries, because the merge is a property of where the position
*lives*, not of what the label says.  So
:func:`require_isolated_margin` refuses a ``book_id`` this system already
holds an arrangement for, under a *different* account.

**An empty book_id names no book, so it names no independent position.**
``nullius`` on its own is the venue's whole balance standing behind whatever
is in it — which is cross margin reached without configuring it.  That is
refused on the book rather than swallowed as a near-miss, the discipline
feature 316's own ``_validated_book_id`` keeps for the same term one module
over: a book that states nothing is not a book this system can keep
independent.

**The verdict is structural rather than advisory.**  :class:`MarginScope`
holds the arrangements already made for a deployment, so "which account does
this book settle against?" is answered by the scope rather than by the caller
remembering — and the refusal comes from the act of making a *second*
arrangement, not from a paragraph a caller must have read.  A caller cannot
merge two books by forgetting to check, because there is nothing to forget:
:meth:`MarginScope.require` is the only way to settle a book and it is where
the comparison happens.  The scope is a plain in-memory value, deliberately
**not** a table: this is a property of one deployment's process and
configuration — the book list is read at startup, per §13.2's "at startup and
daily" cadence — so there is nothing here for a second process to agree on and
nothing to compose.  A deployment that wants the arrangements to outlive the
process records the :class:`BookMargin` values it built, in the configuration
that states them.

**The book's name is spelled verbatim.**  A case-folded or re-spelled
``book_id`` would make one book look like two — feature 316's key derivation
reaches the same term through the same rule, and the book member's rebalance
table (feature 309) is keyed on it — so the term is stripped and otherwise
kept exactly as the deployment spelled it, the near-miss rule that term holds
everywhere else in this member.  The *account* is spelled the same way, and
for the same reason: two spellings of one account is exactly the merge this
feature refuses, so the comparison over accounts is a comparison over the
verbatim strings.

**No clock, no I/O, no table, no component.**  The judgment is a pure function
of the configuration it is handed — the same ask answers the same verdict in
any process, on any day — so there is nothing to persist and nothing to
compose: no ``@register`` is added (the member still registers exactly one
component, feature 310's exchangeInfo store), no seat export is added, and no
migration is touched.  Stdlib only, and import-cheap — ``dataclasses`` and
:mod:`router.errors` — so the factory's scan pays nothing for the gate and a
deployment that never settles a book never constructs one.

**What this module deliberately does not do.**  It does not *open an account*,
*set a leverage*, *read a balance* or *speak to the venue*: the margin mode is
a fact a deployment configures at the exchange, and this gate is the
system's own refusal to run against one it will not trade under.  It does not
*manage margin* or *top up a position*.  It does not *check the venue's own
mode field* — that arrives, if a later feature fetches it, as the configuration
this gate is handed, and a gate that dialled the venue would make asking about
a book's margin a way to fail.  And it does not *halt* anything: the refusal is
the halt, and it happens before an order exists.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

from .errors import CROSS_MARGIN_CODE, RouterCrossMarginError

__all__ = [
    "CROSS_MARGIN",
    "ISOLATED_MARGIN",
    "MARGIN_MODES",
    "BookMargin",
    "MarginScope",
    "require_isolated_margin",
]

#: The mode feature 315's sentence requires: each book's positions margined on
#: their own.  The greppable token a configuration states, and the only value
#: :func:`require_isolated_margin` admits.
ISOLATED_MARGIN = "isolated"

#: The mode the sentence *rejects*: the account's whole balance standing behind
#: every leg.  Named here so the refusal can spell the value it received and
#: the value it required without either being a literal in a message.
CROSS_MARGIN = "cross"

#: The closed mode vocabulary — exactly the two arrangements a book's positions
#: can settle under, and the set the value layer validates against so a mode
#: this system has never heard of is refused rather than mapped onto one of
#: these.  Built from the two names above, the discipline
#: :data:`~router.submission_health.ORDER_SUBMISSION_OUTCOMES` keeps for its
#: own vocabulary: one spelling, one home.
MARGIN_MODES = frozenset({ISOLATED_MARGIN, CROSS_MARGIN})


def _validated_book_id(value: Any) -> str:
    """Return ``value`` as a book identity, or refuse what cannot be one.

    Non-empty text, stripped — the same rule :func:`router.client_order_id.
    _validated_book_id` holds the same term to, and for the same reason: the
    term is one identity across this member's features (feature 316 folds it
    into the order's key; feature 309 keys its rebalance table on it), so a
    spelling this gate accepted and that derivation refused would be one book
    wearing two names.  The blank is refused on the *feature's* own ground too:
    a book that states nothing is not a position this system can keep
    independent — it is the venue's whole balance standing behind whatever is
    in it, which is cross margin reached without configuring it.
    """
    if not isinstance(value, str) or not value.strip():
        raise RouterCrossMarginError(
            f"{CROSS_MARGIN_CODE}: book_id must be non-empty text, got "
            f"{value!r} ({type(value).__name__}); isolated margin is *per "
            "book*, so a book that states no name names no independent "
            "position to margin (feature 315)"
        )
    return value.strip()


def _validated_account(value: Any) -> str:
    """Return ``value`` as the account a book's positions settle against.

    Non-empty text, stripped, otherwise **verbatim** — and the verbatim part is
    load-bearing here rather than a stylistic echo of the sibling validator: the
    account is the thing that merges, so the comparison
    :func:`require_isolated_margin` makes over two books' accounts has to be a
    comparison over the spellings the deployment actually configured.  An
    account that normalized ``Umbrella`` and ``umbrella`` into one value would
    be this module deciding two accounts are one, which is exactly the
    judgment the venue owns.

    A blank is refused because it is the assertion that merged everything:
    a position with no account named is not a position this system can keep
    away from another book's.
    """
    if not isinstance(value, str) or not value.strip():
        raise RouterCrossMarginError(
            f"{CROSS_MARGIN_CODE}: account must be non-empty text, got "
            f"{value!r} ({type(value).__name__}); two books settling against "
            "one account are one position with N legs however each book is "
            "labelled, so an arrangement that names no account names no "
            "separation either (feature 315)"
        )
    return value.strip()


def _validated_mode(value: Any) -> str:
    """Return ``value`` as a margin mode, or refuse it by name.

    Membership is tested against the *string* the value would have to be rather
    than against the value itself, because ``frozenset`` membership raises
    :class:`TypeError` on an unhashable argument — a ``[]`` here is a crash, not
    a ``False`` — and a caller offering a list to a vocabulary of tokens
    deserves this member's refusal naming the value, the same trap
    :func:`router.submission_result._require_outcome` catches for its own set.

    Refused rather than defaulted: the sentence admits one mode and rejects
    one, and a value outside the closed vocabulary is neither.  Resolving it to
    :data:`ISOLATED_MARGIN` would be this module *configuring* a book the
    deployment never configured, and resolving it to :data:`CROSS_MARGIN` would
    be inventing the fault it reports.
    """
    if not isinstance(value, str) or value not in MARGIN_MODES:
        raise RouterCrossMarginError(
            f"{CROSS_MARGIN_CODE}: a margin mode is one of "
            f"{sorted(MARGIN_MODES)}, got {value!r} ({type(value).__name__}); "
            "the mode says whether a book's positions stand on their own or "
            "share the account's whole balance, and a value outside the "
            "vocabulary states neither (feature 315)"
        )
    return value


@dataclass(frozen=True)
class BookMargin:
    """One book's margin arrangement: the book, its mode, and its account.

    The value :func:`require_isolated_margin` answers and the value a
    configuration records — the three facts the sentence's judgment is made
    over, kept together because a verdict that returned only "isolated" would
    lose *which* book is isolated and *against what*.

    * ``book_id`` — whose positions these are.  The deployment's own name for
      the book, the same term feature 316 folds into the order's key and
      feature 309 keys its rebalance table on.
    * ``account`` — where the positions live, which is what actually decides
      whether two books are one position with N legs.  Two arrangements with
      one account are one position whatever their ``mode`` fields say, which is
      why :class:`MarginScope` compares this field rather than the label.
    * ``mode`` — :data:`ISOLATED_MARGIN` or :data:`CROSS_MARGIN`, from
      :data:`MARGIN_MODES`.  Constructible with ``cross`` **on purpose**: the
      value describes an arrangement, and a value type that could not express
      the arrangement this feature refuses could not be compared against.  The
      *enforcement* is the gate's, not the value's — see
      :func:`require_isolated_margin`.

    All three are canonicalised at construction — names stripped and otherwise
    verbatim, the mode validated against the vocabulary — so two arrangements
    built from one configuration compare equal however the caller came by the
    spellings, and a scope can key its books on the values it was handed.
    Frozen, and hashable: an arrangement can stand as its own key.
    """

    book_id: str
    account: str
    mode: str = ISOLATED_MARGIN

    def __post_init__(self) -> None:
        object.__setattr__(self, "book_id", _validated_book_id(self.book_id))
        object.__setattr__(self, "account", _validated_account(self.account))
        object.__setattr__(self, "mode", _validated_mode(self.mode))

    @property
    def is_isolated(self) -> bool:
        """Whether this book's positions stand on their own.

        The sentence's claim about one arrangement, spelled as its own name so
        a caller reading a record writes ``if margin.is_isolated:`` rather than
        comparing against a token it has to have imported.  It is deliberately
        a *reading* of the mode rather than the enforcement: this value can
        describe a cross arrangement, and the refusal to trade under one
        belongs to :func:`require_isolated_margin`.
        """
        return self.mode == ISOLATED_MARGIN


def require_isolated_margin(
    *,
    book_id: Any,
    account: Any,
    mode: Any = ISOLATED_MARGIN,
    scope: MarginScope | None = None,
) -> BookMargin:
    """Feature 315's verb: settle a book under isolated margin, or refuse.

    app_spec.xml, "Order Routing & Venue Filters", feature 315: *System uses
    isolated margin per book, which rejects a cross-margin configuration that
    would merge independent positions.*  This is that sentence as one call: it
    answers the :class:`BookMargin` for the book being configured, and it
    raises :class:`~router.errors.RouterCrossMarginError` when the
    configuration would merge two books' positions.

    Each argument is a required keyword except ``mode`` and ``scope``.
    ``book_id`` and ``account`` carry no default because a default would be
    this module naming a book or an account the deployment never stated — the
    law feature 316's own ``rebalance_ts`` states for its term, and the same
    one here.  ``mode`` defaults to :data:`ISOLATED_MARGIN`, which is the
    feature's own sentence rather than a convenience: *system uses isolated
    margin* is the configured default, and a caller states another mode only to
    state the configuration being judged.

    **Two refusals, in this order.**  The mode is judged first — a
    ``cross`` arrangement is refused by name, before the scope is consulted at
    all, because an arrangement this system will not trade under is refused for
    its own sake and not only when it happens to collide with another book.
    Then the account is judged against what ``scope`` already holds: a book
    pointed at an account *another* book already settles against is refused,
    whether or not either is labelled ``cross``, because that is the merge the
    sentence is about.

    A book's *own* entry is not a collision, and it is deliberately left to the
    scope to decide what re-stating one means — see :meth:`MarginScope.require`
    on why a reload is a no-op and a re-point is a configuration change rather
    than a merge.  This function judges one ask against other books; it does
    not police a book against itself.

    ``scope`` is optional so the mode rule can be checked on its own, for a
    caller settling a deployment's first book or a configuration validator that
    has no scope yet.  With no scope there is nothing to compare accounts
    against, and no merge is possible between a book and nothing.

    Returns the frozen :class:`BookMargin` carrying the three canonicalised
    facts, so a caller that records the arrangement has the whole of it rather
    than the sentence's verdict alone.
    """
    book = _validated_book_id(book_id)
    settled = _validated_account(account)
    chosen = _validated_mode(mode)
    if chosen != ISOLATED_MARGIN:
        raise RouterCrossMarginError(
            f"{CROSS_MARGIN_CODE}: book {book!r} is configured for "
            f"{chosen!r} margin against account {settled!r}, and this system "
            f"trades {ISOLATED_MARGIN!r} only; cross margin converts N "
            "independent positions into one position with N legs, and a "
            "single leg's liquidation cascades into the rest (§13.2, C9) — "
            f"margin book {book!r} on its own account (feature 315)"
        )
    if scope is not None:
        for other, arrangement in scope:
            if other != book and arrangement.account == settled:
                raise RouterCrossMarginError(
                    f"{CROSS_MARGIN_CODE}: book {book!r} would settle against "
                    f"account {settled!r}, which book {other!r} already "
                    "settles against; two books sharing one margin account "
                    "are one position with N legs whatever each book is "
                    "labelled, and a single leg's liquidation cascades into "
                    "the rest (§13.2, C9) — give each book its own account, "
                    "which is what *isolated margin per book* means (feature "
                    "315)"
                )
    return BookMargin(book_id=book, account=settled, mode=chosen)


@dataclass
class MarginScope:
    """The margin arrangements a deployment has already made, by book.

    The structural half of the feature: a deployment settles its books through
    :meth:`require` rather than through a bare call to
    :func:`require_isolated_margin`, so *"which account does this book settle
    against?"* is answered by the scope the orders are being configured in
    rather than by the caller remembering to compare.  A caller cannot merge
    two books by forgetting to ask: the comparison happens inside the one act
    that settles a book.

    Mutable and in-memory, deliberately.  This is one process's view of one
    deployment's configuration — read from the book list at startup, per
    §13.2's startup-and-daily cadence — so there is no second process to agree
    with and nothing for a table (or a component, or a migration) to hold.  A
    deployment that wants the arrangements to survive a restart records the
    :class:`BookMargin` values it built, in the configuration that states them;
    re-:meth:`require`-ing the same book against the same account on reload is
    an idempotent no-op, which is what makes that reload safe.

    The scope is *empty* until a book is settled through it, and it holds the
    arrangement that was actually made rather than the ask: a refused
    configuration leaves no entry behind, so a deployment that fixes its book
    list and retries is judged against what stands, not against what was
    rejected.  Iteration answers ``(book_id, BookMargin)`` pairs in the order
    the books were settled — a plain reading of what is held, so a
    configuration report and the refusal's own search see the same thing.

    **A scope holds isolated arrangements only.**  Every entry is checked at
    construction, so the invariant holds by construction rather than at each
    call site — and that is the feature, not a stricter reading of it: the
    scope *is* the structure that makes the sentence structural, so a scope
    any read path could be pointed at must not be one a deployment can put a
    cross arrangement into.  :class:`BookMargin` still expresses ``cross``,
    because it has to be the value a refusal names; describing an arrangement
    and holding it as one of the deployment's own are different acts, and
    only the first is one this system has a use for.
    """

    _arrangements: dict[str, BookMargin] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        # Keyed by the canonical book name, so a scope handed a mapping (or
        # re-constructed) cannot hold two entries for one book under two
        # spellings of its name -- the same near-miss this module refuses for
        # the term everywhere else.
        if not isinstance(self._arrangements, Mapping):
            raise RouterCrossMarginError(
                f"{CROSS_MARGIN_CODE}: a scope is described by a mapping of "
                f"book id to arrangement, got "
                f"{type(self._arrangements).__name__}; an initialiser that "
                "states no arrangements by book states nothing a second book "
                "could be compared against (feature 315)"
            )
        canonical: dict[str, BookMargin] = {}
        for book_id, arrangement in self._arrangements.items():
            if not isinstance(arrangement, BookMargin):
                raise RouterCrossMarginError(
                    f"{CROSS_MARGIN_CODE}: a scope holds BookMargin "
                    f"arrangements, got {arrangement!r} "
                    f"({type(arrangement).__name__}) for book {book_id!r}; an "
                    "entry that is not an arrangement states no account, so "
                    "nothing can be compared against it (feature 315)"
                )
            name = _validated_book_id(book_id)
            if name != arrangement.book_id:
                raise RouterCrossMarginError(
                    f"{CROSS_MARGIN_CODE}: the scope's key {book_id!r} and the "
                    f"arrangement's own book {arrangement.book_id!r} are two "
                    "names for one entry; a scope that filed an arrangement "
                    "under a name its record disagrees with would judge the "
                    "next book against the wrong account (feature 315)"
                )
            # A scope never *holds* a cross arrangement, and that is the
            # feature rather than a stricter reading of it: the scope is the
            # structure that makes the sentence structural, so the invariant
            # has to hold by construction rather than at each call site.  A
            # scope that could contain one would be a scope any read path
            # could be pointed at, and this system does not trade under one.
            # ``BookMargin`` still *expresses* cross -- it has to, or it could
            # not be the value a refusal names -- but expressing an
            # arrangement and holding it as a deployment's own are different
            # acts, and only the first is one this system has any use for.
            if not arrangement.is_isolated:
                raise RouterCrossMarginError(
                    f"{CROSS_MARGIN_CODE}: book {name!r} is filed under "
                    f"{arrangement.mode!r} margin, which a margin scope never "
                    "holds; the scope is what a deployment settles its books "
                    "through, and cross margin converts N independent "
                    "positions into one position with N legs, and a single "
                    "leg's liquidation cascades into the rest (§13.2, C9) — "
                    "describe the cross arrangement with a BookMargin value on "
                    "its own, and settle books here under isolated margin "
                    "(feature 315)"
                )
            canonical[name] = arrangement
        self._arrangements = canonical

    # -- Reading ---------------------------------------------------------------

    def account_for(self, book_id: Any) -> str | None:
        """The account ``book_id`` already settles against, or ``None``.

        ``None`` for a book this scope has never seen — deliberately not a
        fallback to some default account, which would be this module inventing
        a merge: a book with no arrangement is a book that has made none, and
        the first arrangement for it is free to name any account.
        """
        arrangement = self._arrangements.get(_validated_book_id(book_id))
        return None if arrangement is None else arrangement.account

    def margin_for(self, book_id: Any) -> BookMargin | None:
        """``book_id``'s arrangement, or ``None`` when it has none."""
        return self._arrangements.get(_validated_book_id(book_id))

    def books(self) -> tuple[str, ...]:
        """The books this scope holds arrangements for, in settle order."""
        return tuple(self._arrangements)

    def accounts(self) -> tuple[str, ...]:
        """The accounts in use, in settle order and without repetition.

        The deployment's margin footprint as one tuple: a caller that must
        answer *how many independent positions is this book list actually
        worth?* counts this rather than the books, because two books on one
        account are one position with N legs — which is the whole of the
        sentence this module enforces.
        """
        seen: dict[str, None] = {}
        for arrangement in self._arrangements.values():
            seen.setdefault(arrangement.account, None)
        return tuple(seen)

    def __iter__(self) -> Iterator[tuple[str, BookMargin]]:
        return iter(self._arrangements.items())

    def __len__(self) -> int:
        return len(self._arrangements)

    def __contains__(self, book_id: object) -> bool:
        try:
            name = _validated_book_id(book_id)
        except RouterCrossMarginError:
            return False
        return name in self._arrangements

    # -- Feature 315's verb ----------------------------------------------------

    def require(
        self,
        *,
        book_id: Any,
        account: Any,
        mode: Any = ISOLATED_MARGIN,
    ) -> BookMargin:
        """Settle a book under this scope, or refuse the merge.

        Feature 315's verb with the deployment's own arrangements behind it: the
        mode is judged as :func:`require_isolated_margin` judges it, and the
        account is judged against every *other* book this scope already holds.
        On success the arrangement is recorded and returned, so the *next* book
        is judged against it — which is what makes the sentence structural
        rather than advisory.

        **A refusal records nothing.**  The arrangement that was rejected never
        enters the scope, so a deployment that gives a colliding book its own
        account and retries is judged against the books that stand rather than
        against what was rejected.

        **One book, one entry, and re-stating it is not a merge.**  A book's own
        entry is never compared against itself — the scope is asking *does this
        book now share an account with a different book*, and a book shares
        nothing with itself.  So the two things a reload does are the two things
        a reload should do:

        * re-stating a book against the account it already holds is an
          **idempotent no-op** — the arrangement is answered unchanged and the
          scope is as it was, which is what makes a startup-and-daily reload
          (§13.2) safe to repeat;
        * re-pointing a book at a *different* account **moves it**, and the
          scope's entry is replaced — because which account a book settles
          against is the deployment's configuration, and a configuration that
          changed is a configuration the deployment is entitled to state.  The
          merge this feature refuses is two books on one account *at rest*,
          never a book being reconfigured away from an account: refusing the
          re-point would leave a deployment unable to correct a book's account
          at all, and the arrangement that would have collided is gone the
          moment the entry is replaced.

        A re-point is judged against the *other* books, so it is refused when
        the new account is one they hold — the merge is the same merge however
        the book arrived at it.
        """
        arrangement = require_isolated_margin(
            book_id=book_id,
            account=account,
            mode=mode,
            scope=self,
        )
        self._arrangements[arrangement.book_id] = arrangement
        return arrangement

    @classmethod
    def from_arrangements(
        cls, arrangements: Mapping[str, Any] | Iterable[Any]
    ) -> MarginScope:
        """A scope holding ``arrangements``, for a deployment being described.

        Two shapes, both read as the same thing: a mapping of book id to
        arrangement, or any iterable of arrangements that each carry their own
        ``book_id``.  The second is what a configuration file's book list
        produces once each entry has been settled, and it is accepted so that a
        caller holding that list does not have to re-key it into a mapping to
        describe a deployment it already has.

        Every entry is validated as :meth:`require` would validate it —
        including the account comparison, so a pair of entries that *already*
        merge is refused here rather than being smuggled into a scope by
        construction — which is the one place a caller could otherwise skip the
        sentence entirely.
        """
        scope = cls()
        if isinstance(arrangements, Mapping):
            entries = list(arrangements.values())
        else:
            entries = list(arrangements)
        for entry in entries:
            if not isinstance(entry, BookMargin):
                raise RouterCrossMarginError(
                    f"{CROSS_MARGIN_CODE}: a deployment's arrangements are "
                    f"BookMargin values, got {entry!r} "
                    f"({type(entry).__name__}); settle each book through "
                    "require_isolated_margin so the account comparison is made "
                    "(feature 315)"
                )
            scope.require(book_id=entry.book_id, account=entry.account, mode=entry.mode)
        return scope
