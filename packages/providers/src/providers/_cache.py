"""The depth role's cache economics — feature 200's price axis and measured rate.

app_spec.xml, "LLM Provider Tiering & Agent Pinning", feature 200: *System
persists the measured cache hit rate per campaign, because the depth model
is selected on cache-hit input price rather than list price.*  docs/
nullius-tech-architecture.md §14.1 states the economics this module
implements, under its own heading:

    The depth role's cost is almost entirely re-reading a large,
    append-only, stable prefix.  Sibling calls within a batch share an
    identical history prefix, so the cacheable segment is both large and
    stable.

    Prompt caching is worth **4–5×** here.  Providers differ enormously
    on cache-hit input pricing — an order of magnitude or more — and on
    this access pattern that difference dominates the headline rate
    card.  Select the depth model on cache-hit price, not list price.

The feature's sentence carries both halves of that paragraph, joined by
its *because*: the **selection** half (a depth model chosen on the
cache-hit input price, the axis §14.1 says dominates) and the
**measurement** half (the hit rate a campaign's calls actually realised,
persisted per campaign).  The join is not ornamental — the rate is the
evidence the selection's axis is the right one.  §14.2's corrected cost
model ends on exactly this sentence: *"Tiering saves ~6.5×, and the
saving comes almost entirely from the depth role's cache-hit rate."*  A
deployment that selected on cache-hit price but never measured the hit
rate would be running the whole tiering story on faith: the premise —
that the history prefix is large, stable and shared — is a property of
the access pattern, and the rate is the number that says whether the
campaign's calls actually enjoyed it.

Why the prices are configured, not constant
-------------------------------------------

No price is spelled in this module's code, and the restraint is the one
features 201 and 202 keep for their fractions and their windows.
§14.2's own preamble is *"Verified 2026-09-19.  Rates move monthly and
several below are explicitly promotional.  Re-verify before budgeting;
the **selection logic** is stable, the numbers are not."* — and its
volatility list even carries a cache-adjacent event (*"DeepSeek moved to
peak/off-peak billing on 2026-08-17 and its cheapest input rose ~61%
over 90 days"*).  §14.2's own comparison — DeepSeek's $0.006/M cache
hits, ~80× below Claude's cached input and ~4× below Gemini's — is the
*shape* of the ordering this module implements, and the suite's fixture
card carries those numbers as its data so a test reads like the
deployment it stands in for, while the module holds only the comparison.

The sentence's three halves
----------------------------

The feature decomposes the way its siblings do — a configuration, a
choice, and a persistence — with the measurement playing the role the
chosen window plays in feature 202:

* :class:`CachePrice` — **the configuration's unit**: one model's cache
  pricing as its rate card describes it — the model's name, its
  ``input_price`` (the list price of an input token, per million), and
  its ``cache_hit_price`` (what an input token costs when served from
  the provider's cached-context prefix).  Shape-validated on
  construction: the name is a non-empty string, both prices are finite
  non-negative numbers, and the hit never costs more than the miss — a
  card whose cache hits are dearer than its cold reads contradicts the
  feature's own premise rather than describing an unusual provider.

* :class:`CachePricing` — **the configuration**: the frozen collection
  of the card's prices, one per model, sorted into one canonical order
  so two cards stating the same prices compare equal.  Empty is legal
  and describes no model, which for a selection is the same
  *nothing is configured here* :class:`providers.BatchPricing`'s empty
  card states — and the selection refuses it the same way, by naming
  the first candidate it cannot price, rather than by guessing.

* :func:`select_depth_model` — **the choice**: among the depth-model
  candidates offered, the one whose :class:`CachePrice` carries the
  lowest **cache-hit input price** — §14.1's *"select the depth model on
  cache-hit price, not list price"* as one comparison.  A candidate the
  card does not price is refused as
  :class:`~providers.UnpricedModelError`, never silently skipped: the
  fallback a skip would invite is the list price, the exact axis the
  sentence's *because* exists to refuse.

* :class:`SelectedDepthModel` — **the choice's answer**: the chosen
  model with **both** its prices, so a caller reading the answer sees
  the ordering it was decided on — the cheap hit *and* the dearer (or,
  on a tie, cheaper) miss — rather than a name floating free of the
  economics that picked it.  The :attr:`~SelectedDepthModel.cache_advantage`
  property answers §14.1's *"worth 4–5×"* figure: how many times
  cheaper a hit is than a miss on the chosen card.

* :class:`DepthCacheRates` — **the persistence**: the store that
  measures one campaign's cache hit rate from its calls' token
  accounting and answers the record the table holds, and this module's
  registered component (see
  :data:`providers.DEPTH_CACHE_RATE_COMPONENT`).  Its
  :meth:`~providers.DepthCacheRates.measure` is the feature's sentence
  as one call — total the usages, prove the campaign was planned,
  insert the row, read it back — because a rate measured and not
  persisted is the sentence with its first half missing.

The selection never falls back to the list price
------------------------------------------------

The load-bearing refusal of the choice half.  Every rate card states a
list price; not every card states a cache-hit price; and the cheapest
model on the list is not the cheapest on the hit — §14.2's own depth
row is the worked example, where the model with the *higher* list input
price ($0.30 against $0.25) is 4× cheaper on the hit ($0.006 against
~$0.024).  A selection that skipped an unpriced candidate, or ranked it
on its list price, would answer the question §14.1 explicitly says not
to ask — and would answer it silently, which is worse than asking it
wrong: the deployment would read a model name out of
:func:`select_depth_model` and have no way to know the axis it was
chosen on.  So the card entry states both prices or it does not exist
(:class:`CachePrice` has no optional cache-hit field), and a candidate
without a card entry is refused by name.

The measurement, and why it reads only two counts
-------------------------------------------------

The rate is measured from the token accounting feature 192's
completions already carry: :attr:`providers.Usage.input_tokens` (the
billed input) and :attr:`providers.Usage.cache_read_tokens` (the portion
of that input the provider served from its cached-context prefix — a
subset of the input, which is why :meth:`providers.Usage.total_tokens`
does not add it on top).  The campaign's rate is the one fraction

    cache_read_tokens ÷ input_tokens

totalled over the campaign's calls, and the store computes it from the
counts rather than accepting a caller's pre-formed ratio, because
*measured* is the sentence's own word: a rate this feature persisted on
trust would be an estimate wearing a measurement's authority — the same
reason §14.2's corrected cost model is called a correction.  The
recognition reads exactly those two counts and no others: output tokens
are the cost model's axis, not this feature's, and a field the
measurement does not read is a field that would drift
(:mod:`providers._depth` states the discipline for its own record).

The persistence is a member-owned table
---------------------------------------

The row lands in ``depth_cache_rate``, a table **this member owns and
creates lazily** (``CREATE TABLE IF NOT EXISTS`` on the store's first
write) — the contract :mod:`bootstrap._pool` states for its own
``bootstrap_world`` table and :mod:`providers._schedule` restates for
``depth_run_window``, not the one :mod:`providers._pin_store` follows
for ``node``.  The difference is which feature owns the schema: no
migration declares this row, exactly as no migration declared the
bootstrap pool's worlds, and a member that refused to create its own
table would be refusing its own feature.  The shared-migration chain is
still not edited.  The ``campaign`` table beside it is probed
read-only, never created: it is ``0111``'s (feature 104), its planned
rows written by feature 232's planner, and the store reads it for
exactly one question — *was this campaign ever planned?* — the same
``sqlite_master`` idiom :mod:`providers._schedule` uses, refusing an
unknown id as :class:`~providers.UnplannedCampaignError`.

One campaign, one measurement, one row
--------------------------------------

The table's key is ``campaign_id`` — one measurement per campaign,
because one campaign is one run of the discovery loop (§5: *"one
campaign = one discovery tree"*) and the run's calls are what they are:
the totals are re-derivable from the completions that served the
campaign and from nothing else.  The idempotence is the one
:class:`~providers.RunWindowConflictError` states for windows, with
both halves deliberate:

* *re-issuing the identical measurement* — same campaign, same totals —
  returns the stored record, including its original ``measured_at``.  A
  retry is the same measurement arriving twice, and the row *is* the
  measurement: the retry did not move the moment it was taken.

* *a measurement naming different totals* is refused as
  :class:`~providers.CacheRateConflictError`, naming both totals and
  both rates — the same campaign cannot have hit cache at two rates,
  and a caller meeting the refusal learns which value is stored and
  which its own ask totalled.  The repair is to read the stored record
  with :meth:`~providers.DepthCacheRates.get`, or — if the campaign
  genuinely ran twice — to plan the second run under its own campaign
  id, so each measurement measures one run.

What the row carries, and why
-----------------------------

* ``campaign_id`` — the planned campaign's id, canonical UUID text,
  ``NOT NULL PRIMARY KEY`` for the reason ``0111`` spells its own key
  that way: SQLite accepts NULL in a bare ``PRIMARY KEY``, and a second
  NULL-keyed rate row would split a measurement from its campaign.

* ``input_tokens`` / ``cache_read_tokens`` — the two counts the rate is
  the quotient of, **not the rate itself**.  The totals are the record
  and the rate is derived — the same derived-not-stored split
  :attr:`providers.RunWindow.duration` and
  :meth:`discovery.CampaignRecord.planted_nulls` make — for a reason
  specific to this feature: a stored ratio cannot be re-verified (two
  numbers that agree with nothing), while two counts can be checked
  against each other (the hit cannot exceed the input it is a portion
  of) and against the campaign's own completions.  A float column would
  also round the rate — 29/30 is exact as a quotient of the two stored
  ints and is no binary fraction at all.

* ``measured_at`` — the instant of the measurement, writer-stamped (no
  engine ``DEFAULT``, for the reason :mod:`bootstrap._pool` gives: a
  caller-stamped column never meets SQLite's ``DEFAULT`` grammar, so
  there is no dialect split to carry), in the spine's own ISO-8601 UTC
  text spelling.

Two columns are deliberately absent.  ``output_tokens`` — the rate is a
fact about input, and the cost model is another feature's.  A model
column — which model the rate was measured under is the campaign's own
authoring record (feature 196's serving provider, feature 203's
``agent_model_id`` per node), and a second spelling of it here would be
a copy that can drift from the stratum the ablation actually groups by.

The record read back is re-verified, not merely re-parsed
---------------------------------------------------------

:meth:`~providers.DepthCacheRates.get` builds its answer from the row,
and refuses a row that contradicts its own arithmetic: a cache-read
count exceeding the input count beside it, an input count of zero or a
non-integer total, an instant that does not parse — each refused as the
base :class:`~providers.DepthCacheError`, naming the campaign.  The
read side is where corruption would otherwise be laundered — the same
stance :meth:`providers.AgentModelPins.load` takes for a stored rolling
alias and :meth:`providers.DepthRunWindows.get` takes for a window that
overlaps the peaks stored beside it — and here the laundering would be
worse than a bad number: a rate above 1.0 reading back as a measurement
would be a campaign billed for more cache than it had prompt, a figure
no selection should ever be justified by.

Recognition across the workspace's double import
-------------------------------------------------

Every entry point (:class:`CachePricing` itself,
:func:`select_depth_model`, the store's ``measure``) recognises a
caller's values **by their parts, not their class**, and re-makes them
from this module's classes — the move :func:`providers.require_depth_model`
makes for candidates and :func:`providers.choose_run_window` makes for
pricing cards, for the same load-bearing reason: the module loader
imports every member twice (once by file path under
``_nullius_scanned_<dir>``, once as the importable member), so two
:class:`CachePricing` classes exist over one source file, a dataclass's
generated ``__eq__`` answers ``False`` between them for every value,
and an ``isinstance`` gate would refuse the very card the caller
legitimately built.  Anything carrying the named parts is the value;
the answer is always this module's classes, so equality downstream
means what it says.

Stdlib only, and import-cheap: ``sqlite3``, ``math``, ``uuid``,
``fractions`` and ``datetime``; no third-party import at module scope,
so the factory's scan — which imports this package to fire its
``@register`` — pays nothing for this module.  The store resolves its
path lazily and opens nothing until an operation needs it, so composing
an application never touches a database, and nothing is written until a
caller measures a campaign.
"""

from __future__ import annotations

import math
import os
import sqlite3
import uuid
from collections.abc import Iterable, Mapping
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from ._cache_errors import (
    CacheRateConflictError,
    DepthCacheError,
    UnplannedCampaignError,
    UnpricedModelError,
)

__all__ = [
    "CACHE_READ_TOKENS_COLUMN",
    "DATABASE_URL_ENV",
    "DEPTH_CACHE_RATE_TABLE",
    "INPUT_TOKENS_COLUMN",
    "MEASURED_AT_COLUMN",
    "CachePrice",
    "CachePricing",
    "DepthCacheRates",
    "MeasuredCacheRate",
    "SelectedDepthModel",
    "measure_cache_rate",
    "select_depth_model",
]

#: The environment variable naming the relational store — the one spelling
#: every store in this workspace already uses (the ledger's, the null
#: oracle's seven, the bootstrap pool's, the campaign planner's, the pin
#: store's, the run-window store's), restated here so this store states
#: its own contract and imports nobody else's.
DATABASE_URL_ENV = "DATABASE_URL"

#: The table the measured rate lands in — **this member's own**, created
#: lazily by the store and by nobody else, on the ``bootstrap_world`` /
#: ``depth_run_window`` precedent (a member-owned table for a
#: member-owned fact, no edit to the shared migration chain).  Contrast
#: :data:`CAMPAIGN_TABLE` below, which is a core migration's and is
#: probed read-only.
DEPTH_CACHE_RATE_TABLE = "depth_cache_rate"

#: The planned-campaign table — feature 104's, created by
#: ``migrations/versions/0111_campaign_table.py``, its rows written by
#: feature 232's planner.  Read here for exactly one question — *was
#: this campaign ever planned?* — through a read-only ``sqlite_master``
#: lookup, and never created: the probe-not-create discipline
#: :mod:`discovery.campaign` and :mod:`providers._schedule` follow.
CAMPAIGN_TABLE = "campaign"

#: The column the campaign table's rows are keyed by — ``0111``'s ``id``,
#: the identity the planner mints and every reader of a campaign joins
#: by.  Spelled here so the probe's ``SELECT`` and its refusal name the
#: column the migration owns, not a local invention.
CAMPAIGN_TABLE_ID_COLUMN = "id"

#: The measured-rate row's key: the planned campaign's id, as canonical
#: UUID text.  One campaign is one measurement, so one row per campaign
#: — the whole idempotence story of :class:`DepthCacheRates` hangs off
#: this key.
CAMPAIGN_ID_COLUMN = "campaign_id"

#: The campaign's totalled billed input tokens — the rate's denominator.
#: A count, never the rate: see the module docstring for why the row
#: carries the two totals the quotient is derived from.
INPUT_TOKENS_COLUMN = "input_tokens"

#: The campaign's totalled cache-read tokens — the rate's numerator, and
#: a portion of the input beside it (the cached prefix is part of the
#: prompt), which is the invariant the read path re-verifies.
CACHE_READ_TOKENS_COLUMN = "cache_read_tokens"

#: The instant the measurement was taken — writer-stamped, no engine
#: ``DEFAULT`` (the bootstrap pool's ground: a caller-stamped column
#: never meets SQLite's ``DEFAULT`` grammar, so there is no dialect
#: split to carry).
MEASURED_AT_COLUMN = "measured_at"

#: The parts a card price is recognised by, in declaration order — duck
#: typing across the module loader's double import (see the module
#: docstring), the same tuple :mod:`providers._depth` declares for its
#: candidates and :mod:`providers._batch` for its offerings.
_PRICE_PARTS: tuple[str, ...] = ("model", "input_price", "cache_hit_price")

#: The parts a cache-pricing configuration is recognised by.
_PRICING_PARTS: tuple[str, ...] = ("prices",)

#: The one part a selection candidate is recognised by: the model's
#: name, which is the axis the card is keyed on and the only fact the
#: selection reads off a candidate.  The window and the surcharge
#: threshold are feature 198's to check, and a selection that re-read
#: them would be the second spelling of a criterion that feature states
#: once.
_CANDIDATE_PART = "model"

#: The parts a usage is recognised by for the measurement — exactly the
#: two counts the rate is the quotient of.  ``output_tokens`` is
#: deliberately absent: the recognition reads what the measurement
#: reads, and a field read but unused is a field that would drift (the
#: discipline :mod:`providers._depth` states for carrying no price).
_USAGE_PARTS: tuple[str, ...] = ("input_tokens", "cache_read_tokens")

#: The read-only probe that answers *does this database hold this
#: table?* — ``sqlite_master`` is read (never the rows), which makes the
#: check safe on a database this process has no business writing to; the
#: idiom :mod:`discovery.campaign`, :mod:`bootstrap._census` and
#: :mod:`providers._schedule` all use.  Parameterised, so the table name
#: is a bound value rather than interpolated text.
_TABLE_EXISTS_SQL = "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?"

#: The member-owned table, in one idempotent statement.  Every column is
#: ``NOT NULL`` — a measurement is written whole or not at all, and a
#: row with a denominator but no numerator, or totals but no instant, is
#: half a measurement no auditor could act on.  The key carries
#: ``NOT NULL`` explicitly beside ``PRIMARY KEY`` for the reason
#: ``0111``'s docstring spells: SQLite accepts NULL — and several — in a
#: bare ``PRIMARY KEY``, and a second NULL-keyed rate row would split a
#: measurement from its campaign.
_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {DEPTH_CACHE_RATE_TABLE} (
    {CAMPAIGN_ID_COLUMN}      TEXT NOT NULL PRIMARY KEY,
    {INPUT_TOKENS_COLUMN}     INTEGER NOT NULL,
    {CACHE_READ_TOKENS_COLUMN} INTEGER NOT NULL,
    {MEASURED_AT_COLUMN}      TEXT NOT NULL
)
"""


# ── The configuration ─────────────────────────────────────────────────────────


def _require_model_name(value: object) -> str:
    """Return ``value`` as a model's name, refusing anything else.

    Shape only — whether the named model may serve the depth role is
    feature 198's question, and whether it is *priced* on this card is
    the lookup's.  A name this function refuses is a name no card entry
    could be keyed by and no candidate could be matched: the card's axis
    is the model id (§14.2 states its comparison per model serving the
    depth role), and a value that is not a name cannot key anything.

    Left as the base :class:`DepthCacheError` rather than a subclass, on
    the grounds :mod:`providers._depth_errors` states for its own
    trivia: a malformed description is not a failed selection, and the
    taxonomy splits by question rather than by call site.
    """
    if not isinstance(value, str):
        raise DepthCacheError(
            f"a cache price's model must be a string, got {value!r} "
            f"({type(value).__name__}). The card is keyed by the model id — "
            "architecture §14.2 states its cache-hit comparison per model "
            "serving the depth role — and a value that is not a name cannot "
            "be keyed by one, let alone be selected by the price attached "
            "to it."
        )
    if not value.strip():
        raise DepthCacheError(
            f"a cache price's model must be a non-empty string, got {value!r}. "
            "A blank name describes no model, and every candidate a "
            "selection is offered is matched to its price by this name — "
            "an entry no candidate can be matched to is one this card "
            "cannot answer any selection question with."
        )
    # Canonicalized on the same grounds feature 201's provider names and
    # feature 202's campaign ids are: the name is a lookup key, so
    # ' deepseek-flash ' and 'deepseek-flash' must be one model rather
    # than two that differ by whitespace a config file happened to carry.
    return value.strip()


def _require_price(value: object, field: str, what: str) -> float:
    """Return ``value`` as a finite non-negative price, refusing anything else.

    One guard for the record's two prices, because they fail the same
    way and owe the caller the same explanation.  Three refusals:

    * not a number at all — ``'$0.006'`` (a string off a rate card's
      own page) or ``None`` is config noise a selection would otherwise
      rank on, and a comparison handed a string fails much further from
      the mistake than this guard does;
    * not finite — ``nan`` compares false against everything and would
      sort to an arbitrary position, and ``inf`` is a price no campaign
      can pay, so either would let the selection name a model on a
      number that is not one;
    * negative — a price below zero is not a cheap card but a malformed
      field, refused as data nonsense for the same reason
      :func:`providers._depth._require_token_count` refuses a threshold
      of zero: hiding the malformation inside a comparison it does not
      belong to would let a nonsense card select real models.

    ``bool`` is refused by identity for the reason
    :func:`providers._batch._require_availability` gives: ``True`` is
    the integer 1, and a flag read as a price would silently rank a
    model at one dollar per million tokens while claiming to be a
    stated card.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DepthCacheError(
            f"a cache price's {field} must be a number, got {value!r} "
            f"({type(value).__name__}). {what.capitalize()} — and a value "
            "that is not a number cannot be ranked, compared, or "
            "multiplied into a campaign's cost by the selection that "
            "reads it."
        )
    price = float(value)
    if not math.isfinite(price):
        raise DepthCacheError(
            f"a cache price's {field} must be a finite number, got "
            f"{value!r}. A price that is NaN or infinite is not a fact "
            "about a rate card — NaN compares false against every value "
            "and would sort the model it names to an arbitrary position, "
            "and an infinite price is one no campaign can pay — and "
            "either would let the selection name a model on a number "
            "that is not one."
        )
    if price < 0:
        raise DepthCacheError(
            f"a cache price's {field} must be non-negative, got "
            f"{value!r}. {what.capitalize()}, and a negative price is "
            "not a cheap card but a malformed field — the provider that "
            "pays the campaign to read its cache does not exist, and a "
            "comparison that ranked it would be selecting on nonsense."
        )
    return price


@dataclass(frozen=True)
class CachePrice:
    """One model's cache pricing, as its rate card describes it.

    The three facts feature 200's selection reads, and no others:
    ``model`` — whose price this is, the name a candidate is matched
    against; ``input_price`` — the list price of an input token, per
    million (§14.2's ``$0.30/$1.20`` convention, the first figure); and
    ``cache_hit_price`` — what an input token costs when the provider
    serves it from its cached-context prefix (§14.2's ``$0.006/M cache
    hits``).  Both prices are per million input tokens, the unit the
    registry's own table states, so the two are comparable without a
    conversion and the selection's comparison is one subtraction of
    like against like.

    **Both prices are required, always.**  There is no optional
    cache-hit field and no card entry that states the list price alone,
    for the reason the feature's sentence exists: a card that omitted
    the hit price where it was unknown would leave the selection to
    fall back on the list — silently, which is the one failure mode
    worse than asking the wrong question — and
    :func:`select_depth_model` refuses an unpriced candidate
    (:class:`~providers.UnpricedModelError`) rather than letting the
    card's silence answer for it.  A provider that offers no prompt
    caching at all is described by a ``cache_hit_price`` equal to the
    ``input_price`` — a stated fact the selection reads as *this model
    saves nothing on the hit* — not by an omitted field.

    Construction validates *shape* — a non-empty name, two finite
    non-negative prices, and the one cross-field law that the hit never
    costs more than the miss — and deliberately not the depth role's
    bar: whether the named model may serve depth ≥ 2 is feature 198's
    question, and a card may lawfully price the frontier tier, the
    self-hosted tier and the bootstrap worlds' cheap tier on their own
    rows, for the same reason a 262K-window :class:`~providers.DepthModel`
    constructs happily and only the gate refuses it.

    Frozen and value-equal for the reasons this package's other records
    are: a price is a fact about a provider's rate card, not a field a
    caller tunes, and equality by value is what lets a card configured
    from a rate card's page be compared to one a suite built without
    holding the same objects.
    """

    model: str
    input_price: float
    cache_hit_price: float

    def __post_init__(self) -> None:
        # Field by field in declaration order, then the one cross-field
        # law, so a price malformed in several places is refused for the
        # first one a reader would meet — the same ordering
        # :class:`providers.DepthModel` and :class:`providers.BatchEndpoint`
        # use for their parts.
        object.__setattr__(self, "model", _require_model_name(self.model))
        object.__setattr__(
            self,
            "input_price",
            _require_price(
                self.input_price,
                "input_price",
                "the list price of an input token, per million",
            ),
        )
        object.__setattr__(
            self,
            "cache_hit_price",
            _require_price(
                self.cache_hit_price,
                "cache_hit_price",
                "the price of an input token served from the cached prefix",
            ),
        )
        if self.cache_hit_price > self.input_price:
            raise DepthCacheError(
                f"a cache price's cache_hit_price must not exceed its "
                f"input_price, got {self.model!r} at "
                f"{self.cache_hit_price:g} to read from cache against "
                f"{self.input_price:g} cold. A cache hit is the same token "
                "served from a prefix the provider already holds — it is "
                "what the discount is a discount *of* — so a hit dearer "
                "than a miss is not an unusual provider but a card that "
                "contradicts the feature's own premise, and ranking on it "
                "would select the model that punishes the depth role's "
                "access pattern most. A provider that offers no prompt "
                "caching states cache_hit_price equal to input_price."
            )

    def text(self) -> str:
        """The price's canonical ``"model:list/hit"`` spelling.

        List then hit, per million input tokens — the form refusals
        quote and humans read, and the order that keeps the two halves
        of the sentence's comparison visible wherever the card is
        named: the same role :meth:`providers.PeakWindow.text` and
        :meth:`providers.BatchEndpoint.text` play for their records.
        """
        return (
            f"{self.model}:{self.input_price:g}/{self.cache_hit_price:g}"
        )


@dataclass(frozen=True)
class CachePricing:
    """Which models cost what on the cache-hit axis — feature 200's configuration.

    The frozen collection of the card's :class:`CachePrice` entries, and
    the answer to the question the feature's *because* asks: *selected
    on cache-hit input price rather than list price* — prices stated by
    **whom**, is answered here, per model.

    **Empty is a legal value that describes no model, and it answers no
    selection question.**  The empty card is well-formed (a card built
    incrementally, a config file not yet filled in), but
    :func:`select_depth_model` refuses the first candidate it is offered
    against it as :class:`~providers.UnpricedModelError`, naming the
    model — the same move :class:`providers.BatchPricing`'s empty card
    forces and for the same reason: the selection is keyed by a model's
    name, and an empty card holds no names.  It is deliberately not the
    shape :class:`providers.PeakPricing`'s empty tuple takes (whose
    empty card still answers every scheduling question, *flat by time
    of day*), because the axes differ: a union of minutes reads
    emptiness as *no peak exists*, while a lookup by name reads it as
    *nothing is configured here*.

    **One price per model, and a repeated model is refused.**  A model's
    cache pricing is a single fact looked *up* by name, so two entries
    for one model would make every selection answer depend on which one
    the lookup happened to find: a card claiming one model hits cache at
    both $0.006 and $0.48 would select it two ways.  The record refuses
    the duplicate at construction rather than picking one, naming the
    model, because there is no canonical choice between them — the card
    contradicts itself and the repair is upstream (§14.2's preamble:
    *"Re-verify before budgeting"*).

    Construction accepts any iterable of prices, re-makes each one from
    this module's class (recognised **by its parts** — the
    :data:`_PRICE_PARTS` attributes — the double-import remedy the
    module docstring states, applied at the constructor so that every
    path through the configuration single-sources validation here), and
    **canonicalizes the order**: the tuple is stored sorted by model
    name, so two cards stating the same prices in different orders are
    one value — the determinism :class:`providers.BatchPricing` achieves
    by sorting on provider name, and the reason a card read from a
    config file compares equal to the card a suite built.  Frozen and
    value-equal so a card configured twice compares equal.
    """

    prices: tuple[CachePrice, ...] = ()

    def __post_init__(self) -> None:
        # Any iterable is accepted (a config file's list, a tuple a
        # caller built) and answered as this module's immutable tuple of
        # this module's prices, in canonical model-name order — one
        # class and one order, so equality downstream means what it
        # says.  The value is checked for iterability first, through the
        # same guard the selection path uses, so a non-collection is
        # refused in this module's vocabulary rather than dying inside
        # ``tuple()`` as a bare ``TypeError``.
        entries = tuple(
            _price_from_parts(p) for p in _require_prices(self.prices)
        )
        seen: set[str] = set()
        for entry in entries:
            if entry.model in seen:
                raise DepthCacheError(
                    f"the cache pricing card states a price for "
                    f"{entry.model!r} more than once. A model's cache "
                    "pricing is one fact looked up by the model's name, so "
                    "two prices for one model would make every selection "
                    "answer depend on which one the lookup found — the "
                    "same model selected two ways depending on nothing. "
                    "Keep one price per model; the card is contradictory, "
                    "not merely redundant."
                )
            seen.add(entry.model)
        object.__setattr__(
            self, "prices", tuple(sorted(entries, key=lambda p: p.model))
        )

    @property
    def priced_models(self) -> tuple[str, ...]:
        """The names of the models this card prices, sorted.

        The named fact behind *"selected on cache-hit input price"* —
        a caller offering candidates to a selection wants to know which
        of them the card can rank before it offers them, and the answer
        should say which question it answers.  Derived, never stored —
        the record holds the prices and this is a reading of them, the
        same shape :attr:`providers.BatchPricing.available_providers`
        takes.
        """
        return tuple(p.model for p in self.prices)

    def text(self) -> str:
        """The card's canonical spelling — prices joined, sorted.

        Sorted by the entries' canonical text so two cards stating the
        same prices spell the same, the determinism
        :meth:`providers.BatchPricing.text` gives its own
        configuration.
        """
        return ", ".join(sorted(p.text() for p in self.prices))

    def price_for(self, model: object) -> CachePrice | None:
        """The price for ``model``, or ``None`` when the card holds none.

        The lookup the selection is built on, spelled once so the
        refusal and the ranking read the same card the same way.
        ``None`` means *this card does not price this model* — a
        configuration gap, which :func:`select_depth_model` refuses by
        name rather than reading as *no cache discount available*: the
        two are one silent fallback apart, and confusing them is how a
        model would come to be ranked on the list price its card never
        stated, looking like a decision.
        """
        name = model.strip() if isinstance(model, str) else model
        for entry in self.prices:
            if entry.model == name:
                return entry
        return None


# ── The choice ────────────────────────────────────────────────────────────────


def _require_prices(value: object) -> Iterable:
    """Return ``value`` as an iterable of prices, refusing anything else.

    The one guard for a card's collection, called by
    :class:`CachePricing`'s own constructor **and** by the selection's
    card-recognition helper, so there is a single spelling of the rule
    and a single message for it.  A bare ``tuple()`` over a
    non-iterable raises a ``TypeError`` this module does not own, and a
    caller whose single ``except DepthCacheError`` is meant to catch
    every malformed configuration would find the mistake escaping as a
    builtin instead.

    Two refusals, and the second is not pedantry: a **string is
    iterable**, and iterating one yields its characters —
    ``CachePricing(prices="deepseek")`` would produce nine one-character
    "models" and fail about the wrong thing entirely (or, for a
    one-character string, succeed with a card nobody wrote).  Refused
    as a non-collection, naming what it is, the same move
    :func:`providers._batch._require_offerings` makes.
    """
    if isinstance(value, (str, bytes)):
        raise DepthCacheError(
            f"a cache pricing card's prices must be an iterable of "
            f"CachePrice records, got {value!r} (a {type(value).__name__}). "
            "A string is iterable but is not a collection of prices — "
            "reading one would yield its characters, and a card nobody "
            "wrote is worse than a refusal. Pass a sequence of CachePrice "
            "records."
        )
    if not isinstance(value, Iterable):
        raise DepthCacheError(
            f"a cache pricing card's prices must be an iterable of "
            f"CachePrice records, got {value!r} "
            f"({type(value).__name__}). A card is a collection of models' "
            "prices; a single non-iterable value is not a card this "
            "selection may rank a candidate against."
        )
    return value


def _price_from_parts(value: object) -> CachePrice:
    """Re-make ``value`` as a :class:`CachePrice` from its parts.

    Recognition is structural — the three attributes
    :data:`_PRICE_PARTS` names, read on ``object.__getattribute__`` —
    rather than by class, because the module loader gives every member
    two class objects over one source file (see the module docstring).
    ``object.__getattribute__`` rather than ``getattr`` so an arbitrary
    object's ``__getattr__`` cannot fabricate a price: this function
    decides what may be configured on the card, and a hook that
    answered three parts would be a hook that priced a model.

    The parts are read whatever their types and handed to the
    constructor, which refuses a malformed one precisely — a stub
    carrying ``cache_hit_price='free'`` is told its hit price is not a
    number, not that it is "not a price" — so recognition stays cheap
    and the validation stays single-sourced: there is one shape check,
    the record's own.
    """
    if isinstance(value, CachePrice):
        return value
    try:
        parts = tuple(
            object.__getattribute__(value, part) for part in _PRICE_PARTS
        )
    except AttributeError:
        raise DepthCacheError(
            f"a cache pricing card's prices must be CachePrice records "
            f"({', '.join(_PRICE_PARTS)}), got {value!r} "
            f"({type(value).__name__}). Feature 200 ranks candidates on "
            "the prices this card states, and a value that is not the "
            "record carries no model, no list price and no hit price — "
            "padding the missing fields with guesses would be selecting "
            "models against a card nobody stated."
        ) from None
    return CachePrice(
        model=parts[0],
        input_price=parts[1],
        cache_hit_price=parts[2],
    )


def _require_pricing(value: object) -> CachePricing:
    """Return ``value`` as a :class:`CachePricing`, re-made from its parts.

    The card is recognised by its single ``prices`` part and re-made
    through :class:`CachePricing`'s own constructor, so every path into
    the selection single-sources the shape check — the same move
    :func:`providers._batch._require_pricing` makes for its own
    configuration, and for the same double-import reason.  A value with
    no ``prices`` attribute at all is refused as the base
    :class:`DepthCacheError`, because a selection asked to rank
    candidates needs a card that prices some.
    """
    try:
        prices = object.__getattribute__(value, "prices")
    except AttributeError:
        raise DepthCacheError(
            f"a cache pricing card must be a CachePricing (prices), got "
            f"{value!r} ({type(value).__name__}). Feature 200's selection "
            "ranks depth-model candidates on the cache-hit input prices "
            "this card states, and a value that is not the card carries "
            "no prices to rank them by."
        ) from None
    return CachePricing(prices=tuple(_require_prices(prices)))


def _require_candidates(value: object) -> tuple[str, ...]:
    """Return ``value`` as the model names of the candidates, refusing the rest.

    The candidates are the depth models a caller is choosing between —
    the record feature 198 gates, recognised **by its one ``model``
    part** and not by its class (the double-import remedy again), so a
    caller holding the loader's other class copy is answered the same
    as one holding this module's.  The window and the surcharge
    threshold are deliberately not read: the selection is the
    *economics* half and feature 198's gate the *physics* half, and a
    caller composes them — gate first, then price — because a model
    that cannot hold the history has nothing worth pricing.

    A bare string is refused rather than read as one candidate's name,
    for the reason :func:`providers.require_depth_model` refuses one:
    feature 200 selects among *described* models, and a string is a
    name with no description behind it — the caller that meant it as a
    candidate's name is a ``DepthModel(model=...)`` away from saying so,
    and the caller that passed a list of strings by accident is told
    exactly what shape was wanted instead of watching nine
    one-character models be priced.
    """
    if isinstance(value, (str, bytes)):
        raise DepthCacheError(
            f"select_depth_model's candidates must be an iterable of "
            f"depth-model candidates, got {value!r} (a "
            f"{type(value).__name__}). A single candidate is a described "
            "model — feature 198's DepthModel, or anything carrying its "
            "model name — and a bare string is a name with no card entry "
            "to match; pass the candidates as a sequence."
        )
    if not isinstance(value, Iterable):
        raise DepthCacheError(
            f"select_depth_model's candidates must be an iterable of "
            f"depth-model candidates, got {value!r} "
            f"({type(value).__name__}). A selection chooses between "
            "several candidates, and a single non-iterable value is not "
            "a choice to make."
        )
    names: list[str] = []
    for position, candidate in enumerate(value):
        try:
            name = object.__getattribute__(candidate, _CANDIDATE_PART)
        except AttributeError:
            raise DepthCacheError(
                f"select_depth_model's candidates must each carry a model "
                f"name (the DepthModel shape), got {candidate!r} "
                f"({type(candidate).__name__}) at position {position}. The "
                "selection matches a candidate to its card price by the "
                "model's name, and a value carrying none cannot be priced "
                "— feature 198's gate admits candidates by their window "
                "and threshold, this selection ranks them by their name."
            ) from None
        names.append(_require_model_name(name))
    return tuple(names)


@dataclass(frozen=True)
class SelectedDepthModel:
    """The model the cache-hit price selected, with the prices that did it.

    The choice's three facts as one value: the ``model`` whose card
    price carries the lowest ``cache_hit_price`` of the candidates
    offered, and **both** of its prices — the ``input_price`` it charges
    for a cold read beside the ``cache_hit_price`` it charges for the
    prefix the depth role re-reads.  Both travel with the answer because
    the sentence's *rather than* is the whole finding: a caller handed
    only the winning model would have to take on faith that the list
    price did not pick it, and a caller handed both sees the ordering it
    was decided on — §14.2's own depth row is the worked example, where
    the model with the higher list price is the one worth selecting.

    :attr:`cache_advantage` is **derived, never stored** — how many
    times cheaper a hit is than a miss on the chosen card, the figure
    §14.1's *"Prompt caching is worth 4–5× here"* is an instance of.
    ``None`` when the hit is free (a self-hosted tier whose cache costs
    nothing to serve), because an unbounded multiple is not a number a
    caller can multiply by, and pretending it is zero would be reading
    the largest possible advantage as none.

    Construction validates the same shape :class:`CachePrice` does —
    name, two finite non-negative prices, hit never above miss — so a
    record this module answers is as lawful as the card it came from
    and a hand-built one cannot smuggle in a card the guards refuse.

    Frozen and value-equal, so a choice a suite computes compares equal
    to the choice a caller holds — the same testability every record in
    this package gets from being a value type.
    """

    model: str
    input_price: float
    cache_hit_price: float

    def __post_init__(self) -> None:
        # The card entry's own guards, restated through the same
        # helpers so the answer and the configuration it was read from
        # obey one law.  The cross-field check lives in the constructor
        # below rather than in a shared record to keep this answer
        # constructible from the winning price alone.
        object.__setattr__(self, "model", _require_model_name(self.model))
        object.__setattr__(
            self,
            "input_price",
            _require_price(
                self.input_price,
                "input_price",
                "the list price of an input token, per million",
            ),
        )
        object.__setattr__(
            self,
            "cache_hit_price",
            _require_price(
                self.cache_hit_price,
                "cache_hit_price",
                "the price of an input token served from the cached prefix",
            ),
        )
        if self.cache_hit_price > self.input_price:
            raise DepthCacheError(
                f"a selected model's cache_hit_price must not exceed its "
                f"input_price, got {self.model!r} at "
                f"{self.cache_hit_price:g} against {self.input_price:g}. "
                "The answer of a selection on cache-hit input price "
                "carries the winning card entry's shape, and a hit dearer "
                "than a miss is a card this feature refuses to state."
            )

    @property
    def cache_advantage(self) -> float | None:
        """How many times cheaper a cache hit is than a miss — §14.1's 4–5×.

        ``input_price ÷ cache_hit_price``, derived from the two prices
        the record already carries and never stored beside them, the
        same derived-not-stored split :attr:`providers.RunWindow.duration`
        makes.  ``None`` when ``cache_hit_price`` is zero — the
        self-hosted case, where the multiple is unbounded rather than
        small, and a number is the one thing it is not.
        """
        if self.cache_hit_price == 0.0:
            return None
        return self.input_price / self.cache_hit_price

    def text(self) -> str:
        """The selection's canonical spelling — the winner's card text.

        The same ``"model:list/hit"`` form :meth:`CachePrice.text`
        spells, so a refusal quoting a card and an answer naming its
        winner read in one grammar.
        """
        return (
            f"{self.model}:{self.input_price:g}/{self.cache_hit_price:g}"
        )


def select_depth_model(
    pricing: object,
    *,
    candidates: Iterable,
) -> SelectedDepthModel:
    """Select the depth model whose cache-hit input price is lowest — feature 200's choice.

    §14.1's instruction — *"Select the depth model on cache-hit price,
    not list price."* — as one comparison.  Two arguments and one
    record: the deployment's ``pricing`` card, and the ``candidates``
    offered to the depth role (feature 198's records, or anything
    carrying their ``model`` name — recognised by parts, re-made
    through this module's guards).  The answer is the candidate whose
    card entry carries the lowest ``cache_hit_price``, and it carries
    both that price and the list price beside it, so the caller sees
    the axis the choice turned on — which is the point, because the
    two orderings genuinely disagree: on §14.2's own depth row the
    model with the *higher* list input price is 4× cheaper on the hit,
    and a selection that answered with a name alone would leave a
    caller unable to tell which comparison had just been run.

    **The one refusal is a candidate the card does not price** —
    :class:`~providers.UnpricedModelError`, naming the model and the
    card.  It is the load-bearing refusal of the feature, because the
    two things a silent skip would invite are both the failure the
    sentence's *because* exists to prevent: the unpriced candidate
    would drop out of a selection it was offered to, or be ranked on
    its list price — the number every rate card states and the one
    §14.1 names as answering the wrong question.  A card entry states
    both prices or the model has none; there is no partial entry to
    fall back through, and an empty card refuses the first candidate
    the same way, naming it, rather than answering as though nothing
    were configured.

    **Ties break downward through the card, then through the name.**
    Candidates whose hit prices tie are separated by their list input
    prices (the cheaper miss), and a remaining tie by the model name —
    a total order, so the same card and the same candidates always
    select the same model, whatever order the card or the candidates
    were stated in.  The tie-break is not the selection quietly
    reading the list price: it is consulted only where the primary
    axis has already failed to separate the candidates, which is the
    one place a secondary axis must come from somewhere.

    The card and the candidates are recognised **by their parts, not
    their classes**, and the answer is re-made from this module's
    classes.  The workspace's module loader imports every member twice
    (once by file path under ``_nullius_scanned_<dir>``, once as the
    importable member), so two ``CachePricing`` classes exist over one
    source file, and a dataclass's generated ``__eq__`` answers
    ``False`` between them for every value.  An ``isinstance`` gate
    would therefore refuse the very card the caller legitimately built
    from the deployment's config — the same reason
    :func:`providers.require_depth_model` recognises candidates by
    their parts.

    This function decides **which model the economics picks**, and
    nothing else: it does not gate the candidates on the depth role's
    window or pricing shape (feature 198's
    :func:`providers.require_depth_model` does, and a caller composes
    the two — physics first, then money), does not route the calls
    (feature 201), does not schedule the campaign (feature 202), and
    reads nothing from the disk, the clock, or the network.  A pure
    function of a card and a candidate list, which is what makes the
    comparison free to run as often as the card moves.
    """
    card = _require_pricing(pricing)
    names = _require_candidates(candidates)
    if not names:
        raise DepthCacheError(
            "select_depth_model was offered no candidates: a selection "
            "chooses between depth models, and there is no model here to "
            "rank on the card's cache-hit prices. Feature 198's gate "
            "admits the candidates first (require_depth_model), and the "
            "survivors are what this selection is offered — an empty "
            "offering names nothing to select and nothing to refuse."
        )
    winner: CachePrice | None = None
    for name in names:
        price = card.price_for(name)
        if price is None:
            raise UnpricedModelError(
                f"no cache pricing card describes model {name!r}, so this "
                f"candidate cannot be selected on its cache-hit input "
                f"price. The card states {card.text() or 'no prices'}. "
                "Feature 200 ranks candidates on the price the card "
                "states, and it is deliberately *not* read as *rank this "
                "one on its list price instead*: that fallback is the "
                "exact failure the feature's sentence exists to prevent "
                "(architecture §14.1 — \"Select the depth model on "
                "cache-hit price, not list price\" — because the cheapest "
                "model on the list is not the cheapest on the hit). Add "
                "the model's CachePrice to the card, or stop offering it "
                "as a candidate."
            )
        # The ranking key is the whole story: hit price first, the list
        # price only to break a tie the primary axis left, the name only
        # to make the order total.  Comparing tuples keeps the three
        # clauses in the precedence they are documented in.
        if winner is None or (
            price.cache_hit_price,
            price.input_price,
            price.model,
        ) < (
            winner.cache_hit_price,
            winner.input_price,
            winner.model,
        ):
            winner = price
    assert winner is not None  # names is non-empty and every name is priced
    return SelectedDepthModel(
        model=winner.model,
        input_price=winner.input_price,
        cache_hit_price=winner.cache_hit_price,
    )


# ── The measurement ───────────────────────────────────────────────────────────


def _require_count(value: object, field: str) -> int:
    """Return ``value`` as a non-negative token count, refusing anything else.

    One guard for the measurement's two counted parts, because they
    fail the same way and owe the caller the same explanation.  The
    split from :func:`providers._depth._require_token_count`'s
    ``positive`` to this module's ``non-negative`` is the difference
    between a window a rate card states and an accounting a call
    reports: feature 192's :class:`~providers.Usage` allows an
    ``input_tokens`` of zero (an empty prompt is a shape the record
    can carry), so the measurement refuses a *negative* count here and
    refuses a zero **campaign total** once, at the gate, where the
    feature's own premise — depth calls carry the history — is the fact
    doing the refusing.
    """
    if not isinstance(value, int) or isinstance(value, bool):
        raise DepthCacheError(
            f"a usage's {field} must be an int, got {value!r} "
            f"({type(value).__name__}). The measurement totals the token "
            "counts feature 192's completions carry, and a count that is "
            "not a count cannot be totalled — guessing an interpretation "
            "would be measuring a campaign on an accounting nobody "
            "reported."
        )
    if value < 0:
        raise DepthCacheError(
            f"a usage's {field} must be non-negative, got {value:,}. "
            "Token counts are what the cache hit rate is a quotient of, "
            "and a negative count is not a report a provider could make — "
            "it is a malformed usage, and totalled silently it would "
            "subtract cache the campaign never read."
        )
    return value


def _measure_totals(usages: object) -> tuple[int, int]:
    """Total a campaign's usages into the rate's two counts, refusing the rest.

    The measurement itself: the denominator is the campaign's totalled
    billed input, the numerator its totalled cache reads, and both come
    from the caller's stream of :class:`~providers.Usage` records —
    feature 192's token accounting, recognised by its two counted
    parts (see :data:`_USAGE_PARTS`) and never trusted on a
    pre-formed ratio, because *measured* is the sentence's own word.

    Three refusals, each about a different non-measurement:

    * a stream that is not the accounting — a string (iterable, but of
      its characters), a non-iterable, or an item carrying no token
      counts — is config noise, refused by shape so the mistake is
      heard as a shape mistake;
    * a usage whose ``cache_read_tokens`` exceeds its own
      ``input_tokens`` — the cached prefix is part of the prompt, so a
      single call cannot read more cache than it had prompt; the check
      is per-usage because it is an invariant of each call, which a
      campaign total can hide (one nonsense call inside nine sane ones
      leaves the total looking lawful);
    * a measurement of nothing — no usages at all, or a stream whose
      input totals zero.  The depth role's calls carry the campaign's
      whole history — feature 198's own premise, and the reason a 1M
      window is the bar — so a stream with no input is not the depth
      role's accounting, and a rate persisted from it would be a
      measurement of a campaign that read nothing.
    """
    if isinstance(usages, (str, bytes)):
        raise DepthCacheError(
            f"the usages to measure must be an iterable of Usage records, "
            f"got {usages!r} (a {type(usages).__name__}). A string is "
            "iterable but is not a stream of token accountings — reading "
            "one would yield its characters, and a measurement nobody "
            "took is worse than a refusal."
        )
    if not isinstance(usages, Iterable):
        raise DepthCacheError(
            f"the usages to measure must be an iterable of Usage records, "
            f"got {usages!r} ({type(usages).__name__}). A measurement "
            "totals a campaign's calls, and a single non-iterable value "
            "is not a stream of them."
        )
    input_total = 0
    cache_total = 0
    counted = 0
    for position, usage in enumerate(usages):
        try:
            parts = tuple(
                object.__getattribute__(usage, part) for part in _USAGE_PARTS
            )
        except AttributeError:
            raise DepthCacheError(
                f"the usages to measure must be Usage records "
                f"({', '.join(_USAGE_PARTS)}), got {usage!r} "
                f"({type(usage).__name__}) at position {position}. The "
                "measurement reads the token accounting feature 192's "
                "completions carry, and a value carrying no counts is not "
                "an accounting — padding the missing counts with guesses "
                "would be measuring a campaign on calls nobody reported."
            ) from None
        counted_input = _require_count(parts[0], "input_tokens")
        counted_cache = _require_count(parts[1], "cache_read_tokens")
        if counted_cache > counted_input:
            raise DepthCacheError(
                f"a usage at position {position} reports "
                f"{counted_cache:,} cache-read tokens against "
                f"{counted_input:,} input tokens: the cached prefix is "
                "part of the prompt, so a single call cannot read more "
                "cache than it had prompt. The check is per call because "
                "it is an invariant of each one — a campaign total can "
                "hide a single nonsense report inside nine sane ones — "
                "and totalled silently it would persist a rate above "
                "1.0, a campaign billed for more cache than it read."
            )
        input_total += counted_input
        cache_total += counted_cache
        counted += 1
    if not counted:
        raise DepthCacheError(
            "a measurement of no calls is not a measurement: the usages "
            "to measure were empty, and there is no cache hit rate to "
            "persist for a campaign whose calls were not accounted. "
            "Feature 200's record is a measured fact, and a rate "
            "persisted from an empty stream would be an estimate wearing "
            "a measurement's authority — the row either answers for real "
            "calls or it does not answer."
        )
    if input_total == 0:
        raise DepthCacheError(
            "the usages to measure total zero input tokens, so there is "
            "no cache hit rate to measure: the rate's denominator is the "
            "campaign's billed input, and a stream that read nothing is "
            "not the depth role's accounting. Depth calls at feature "
            "198's own bar carry the campaign's whole history — ~300K "
            "tokens on the average call (architecture §14.2) — so a "
            "zero-input stream names calls the depth role never placed, "
            "and a rate persisted from it would divide by nothing while "
            "claiming to have divided by the campaign."
        )
    return input_total, cache_total


@dataclass(frozen=True)
class MeasuredCacheRate:
    """One campaign's measured cache hit rate: two counts, one instant.

    The row's four facts as one value: the ``campaign_id`` the rate was
    measured for (the planned campaign's canonical UUID text), the
    campaign's totalled ``input_tokens`` and ``cache_read_tokens`` — the
    two counts the rate is the quotient of, **not the rate itself**
    (derived, never stored: two counts can be re-verified against each
    other and against the campaign's completions, and a stored ratio
    agrees with nothing) — the ``measured_at`` instant of the
    measurement, and ``recorded`` — this call's answer state, the same
    field :class:`providers.ScheduledRun` and
    :class:`providers.NodePin` carry: ``True`` when the call that
    returned this record wrote the row, ``False`` when it answered the
    row that was already there (an idempotent retry, or any read from
    :meth:`DepthCacheRates.get`, which never writes).

    :attr:`hit_rate` is the sentence's own figure — an exact
    :class:`~fractions.Fraction`, because a rate is a ratio of two
    integers and the two integers are the record: a float column or a
    float property would round 29/30 into a number no two computations
    agree on, and the comparison a caller most wants to make (*did the
    campaign hit cache at least as often as the last one?*) is exactly
    the comparison a rounding would blur.

    Construction validates the row's own arithmetic — the id is a UUID,
    the counts are non-negative integers, the input is positive, the
    cache read never exceeds the input it is a portion of, the instant
    is aware — so a record this module answers is as lawful as the row
    it came from, and a hand-built one cannot smuggle a rate the guards
    refuse past the store's readers.

    Frozen, so a record that has been read back cannot be edited into a
    different measurement by a caller who kept a reference — the record
    of an observation, like every record in this package.
    """

    campaign_id: str
    input_tokens: int
    cache_read_tokens: int
    measured_at: datetime
    recorded: bool = False

    def __post_init__(self) -> None:
        # The row's own laws, restated on the record so every
        # constructor — the store's readers and a caller's hands —
        # single-sources them here.  The cache-read bound is the
        # invariant the read path re-verifies against a corrupted row,
        # and the positive-input law is the measurement gate's own.
        object.__setattr__(
            self, "campaign_id", _validated_campaign_id(self.campaign_id)
        )
        object.__setattr__(
            self,
            "input_tokens",
            _require_count(self.input_tokens, "input_tokens"),
        )
        object.__setattr__(
            self,
            "cache_read_tokens",
            _require_count(self.cache_read_tokens, "cache_read_tokens"),
        )
        object.__setattr__(
            self, "measured_at", _require_instant(self.measured_at, "a measured cache rate's measured_at")
        )
        if self.input_tokens == 0:
            raise DepthCacheError(
                f"the cache rate measured for campaign {self.campaign_id!r} "
                "carries zero input tokens, so there is no rate to "
                "report: the denominator of the campaign's hit rate is "
                "its billed input, and a measurement that read nothing "
                "is not a measurement of the depth role's calls — they "
                "carry the campaign's whole history (architecture §14.2)."
            )
        if self.cache_read_tokens > self.input_tokens:
            raise DepthCacheError(
                f"the cache rate measured for campaign {self.campaign_id!r} "
                f"carries {self.cache_read_tokens:,} cache-read tokens "
                f"against {self.input_tokens:,} input tokens: the cached "
                "prefix is part of the prompt, so more cache was read "
                "than there was prompt to read from. The row was not "
                "written by this feature — the measurement refuses such "
                "a usage per call — and reading it back as a lawful "
                "measurement would launder a rate above 1.0 into the "
                "record a selection's premise is audited by."
            )

    @property
    def hit_rate(self) -> Fraction:
        """The campaign's cache hit rate — cache-read tokens over input tokens.

        An exact :class:`~fractions.Fraction`, derived from the two
        counts the record carries and never stored beside them: the
        totals are the measurement and this is their quotient, exact
        wherever it is compared — the derived-not-stored split the row
        itself makes, answered as the type that keeps it honest.
        """
        return Fraction(self.cache_read_tokens, self.input_tokens)

    def row(self) -> dict[str, Any]:
        """The record as a store-shaped mapping — a fresh dict per call.

        The column names are the table's own, the discipline
        :meth:`providers.ScheduledRun.row` states: a rendered mapping
        names the same things the same way the store does.  ``recorded``
        is deliberately absent — it is this call's answer state, not a
        fact of the row.
        """
        return {
            CAMPAIGN_ID_COLUMN: self.campaign_id,
            INPUT_TOKENS_COLUMN: self.input_tokens,
            CACHE_READ_TOKENS_COLUMN: self.cache_read_tokens,
            MEASURED_AT_COLUMN: _format_instant(self.measured_at),
        }


# ── The persistence ───────────────────────────────────────────────────────────


def _validated_campaign_id(value: Any) -> str:
    """Validate a campaign id, returning canonical UUID text.

    The same canonicalization :func:`providers._schedule._validated_campaign_id`
    applies, restated rather than imported (each store states its own
    contract): the value joins the campaign table's ``id`` and every
    reader of a campaign's rate, so a mixed-case key would make one
    campaign look like two.  Unlike the planner's write path there is no
    ``None`` case here to let a table mint — this table's key is the
    campaign's own id, and a measurement with no campaign names no run
    whose calls could be accounted.
    """
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, str):
        text = value.strip()
        if text:
            try:
                return str(uuid.UUID(text))
            except ValueError:
                pass
    raise DepthCacheError(
        f"campaign_id {value!r} is not a UUID; a cache hit rate is "
        "measured for a campaign, and the campaign's id is the value "
        f"{CAMPAIGN_TABLE_ID_COLUMN} the campaign table holds and every "
        "reader of this row joins by — an id that cannot join it names "
        "no campaign whose calls could be measured"
    )


def _require_instant(value: object, what: str) -> datetime:
    """Return ``value`` as an aware UTC ``datetime``, refusing the rest.

    The same split :func:`providers._schedule._require_instant` makes:
    aware datetimes of any offset are accepted and converted — an
    instant is an instant — while naive ones are refused by name,
    because a naive value names no instant and a measurement stamped
    with it could not be placed on any timeline an auditor reads.
    """
    if not isinstance(value, datetime):
        raise DepthCacheError(
            f"{what} must be a datetime, got {value!r} "
            f"({type(value).__name__}). A measurement is an observation "
            "taken at an instant, and a value that is not an instant "
            "cannot be one."
        )
    if value.tzinfo is None or value.utcoffset() is None:
        raise DepthCacheError(
            f"{what} must be timezone-aware, got {value!r}: a naive "
            "datetime names no instant, and stamping a measurement with "
            "one would leave a rate that cannot be placed on the "
            "timeline the campaign's own records keep time on."
        )
    return value.astimezone(UTC)


def _format_instant(moment: datetime) -> str:
    """An instant as the spine's ISO-8601 UTC text — ``0111``'s own spelling.

    ``%Y-%m-%dT%H:%M:%S`` plus a three-digit millisecond field and a
    ``Z``, byte-for-byte the form SQLite's
    ``strftime('%Y-%m-%dT%H:%M:%fZ', 'now')`` writes for the campaign
    table's ``created_at`` — restated here (not imported from
    :mod:`providers._schedule`) on the ground that module states
    itself: each store owns its own column spellings.  The
    milliseconds are written by hand because ``strftime``'s ``%f`` is
    six digits and the spine's is three; a format two spellings wide is
    a format that reads back inconsistently.
    """
    utc = moment.astimezone(UTC)
    return f"{utc.strftime('%Y-%m-%dT%H:%M:%S')}.{utc.microsecond // 1000:03d}Z"


def _parse_instant(text: object, campaign: str, column: str) -> datetime:
    """Read back one of the row's instants, refusing a value that is not one.

    The read path's one instant parser, so ``measure``'s read-back and
    ``get`` cannot disagree about the form.  Anything the spine's
    spelling round-trips is accepted; anything else — text another
    dialect wrote, a truncated column, an editing accident — is refused
    naming the campaign and the column, because a measurement whose
    instant does not parse is a row this feature cannot report.
    """
    if not isinstance(text, str) or not text.strip():
        raise DepthCacheError(
            f"the cache rate measured for campaign {campaign!r} carries "
            f"{column} {text!r}, which is not an ISO-8601 UTC instant. "
            "The row was not written by this feature — its instant column "
            "is the spine's own timestamp text, and one that does not "
            "parse is a row this record cannot report."
        )
    try:
        parsed = datetime.fromisoformat(text.strip())
    except ValueError as exc:
        raise DepthCacheError(
            f"the cache rate measured for campaign {campaign!r} carries "
            f"{column} {text!r}, which does not parse as an ISO-8601 "
            "instant. The row was not written by this feature, and an "
            "instant that cannot be read is a measurement this record "
            "cannot report."
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise DepthCacheError(
            f"the cache rate measured for campaign {campaign!r} carries "
            f"{column} {text!r} without a UTC offset: it names no "
            "instant, and a measurement that names no instant cannot be "
            "placed beside the campaign's own records on any timeline."
        )
    return parsed.astimezone(UTC)


def _parse_count(
    value: object, campaign: str, column: str, *, positive: bool
) -> int:
    """Read back one of the row's counts, refusing a value that is not one.

    The read path's one count parser, for both columns (the input's own
    law is positivity, the cache read's non-negativity — the two halves
    of the invariant the record re-states).  SQLite's INTEGER affinity
    answers an integer for a well-formed column and a float or text for
    one that was not written by this feature, and either is refused
    naming the campaign and the column rather than coerced: a
    measurement is only as good as the counts it reads, and a
    ``float(row[1])`` would launder a truncated column into a rate
    nobody measured.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise DepthCacheError(
            f"the cache rate measured for campaign {campaign!r} carries "
            f"{column} {value!r} ({type(value).__name__}), which is not "
            "the integer count this feature writes. The row was not "
            "written by this feature — its count columns are integers — "
            "and a total that is not a count is a measurement this "
            "record cannot report."
        )
    if value < 0 or (positive and value == 0):
        law = (
            "must be positive — it is the rate's denominator"
            if positive
            else "must be non-negative — it is a count of tokens read"
        )
        raise DepthCacheError(
            f"the cache rate measured for campaign {campaign!r} carries "
            f"{column} {value:,}, which {law}. The row was not written by "
            "this feature — the measurement refuses a zero-input or "
            "negative stream before it writes — and reading it back as "
            "lawful would launder a rate nobody could have measured."
        )
    return value


def _sqlite_path(database_url: str) -> Path:
    """Translate a ``sqlite:///`` URL into the filesystem path it names.

    The convention every store in this workspace uses, restated here so
    this store states its own contract and the refusal is this module's
    own error class.  A non-SQLite scheme is refused by name (the
    spec's single-machine allowance is what a stdlib store can speak),
    and an in-memory URL is refused too: a measured rate must outlive
    the measuring call — the selection it justifies and the auditor
    that re-derives it run in another process entirely.
    """
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise DepthCacheError(
            f"unsupported {DATABASE_URL_ENV} scheme {parsed.scheme!r}: this "
            "store speaks sqlite:/// (the spec's single-machine allowance); "
            f"point {DATABASE_URL_ENV} at the sqlite database the campaign "
            "table already lives in"
        )
    if parsed.netloc not in ("", "localhost"):
        raise DepthCacheError(
            f"sqlite {DATABASE_URL_ENV} must not carry a host, got "
            f"{parsed.netloc!r}"
        )
    path = unquote(parsed.path).removeprefix("/")
    if not path or path == ":memory:":
        raise DepthCacheError(
            f"sqlite {DATABASE_URL_ENV} carries no database path: an "
            "in-memory database would die with the connection that opened "
            "it, and a measured cache hit rate must outlive the "
            "measuring call — the selection it justifies and the auditor "
            "that re-derives it from the campaign's completions both read "
            "it in another process"
        )
    return Path(path)


class DepthCacheRates:
    """The store that measures campaigns' cache hit rates and persists them.

    Constructed with the database URL it writes to;
    :meth:`measure` is feature 200's sentence as one call — total the
    usages, prove the campaign was planned, insert the row, read it
    back — and :meth:`get` reads one campaign's measured rate.  The
    class resolves its path lazily, so constructing one performs no
    I/O: composition-time work must not touch the disk, the contract
    every store in this workspace states.  The table
    (:data:`DEPTH_CACHE_RATE_TABLE`) is this member's own, created
    lazily on the store's **first write** — :meth:`get` on a store that
    has never measured reads ``sqlite_master``, finds no table, and
    answers ``None``, so a read never brings a schema into being.

    The store holds no cache of the measurements it wrote: the row is
    the only record of what was measured, so it is the only thing an
    answer is drawn from — the same stance
    :class:`providers.DepthRunWindows` states, for the same reason.  A
    memo of measured campaigns would make *what rate did this campaign
    hit cache at?* a question about this process's history rather than
    about the world.
    """

    def __init__(self, database_url: str) -> None:
        if not isinstance(database_url, str) or not database_url.strip():
            raise DepthCacheError(
                f"{DATABASE_URL_ENV} must be a non-empty database URL"
            )
        self._database_url = database_url.strip()
        # Resolved on first use rather than at construction: building the
        # store is composition-time work and must not touch the disk.
        self._path: Path | None = None

    # -- Construction -------------------------------------------------------

    @classmethod
    def resolve(cls, env: Mapping[str, str] | None = None) -> DepthCacheRates | None:
        """The store ``DATABASE_URL`` names, or ``None`` when it names none.

        An empty or whitespace-only value counts as unset.  Absent is
        not an error: it is a deployment without a relational store,
        which composes no cache-rate component — a discoverable state,
        not an exception — while the caller that must persist a
        campaign's measured rate is the caller that must not find
        itself in it, for the reason
        :func:`providers.build_depth_run_windows` states on its own
        ``None``: the caller that needs this row treats it as a refusal
        to proceed rather than as a store that happened to find
        nothing.
        """
        source = os.environ if env is None else env
        raw = source.get(DATABASE_URL_ENV, "").strip()
        if not raw:
            return None
        return cls(raw)

    @property
    def database_url(self) -> str:
        """The database URL this store writes to."""
        return self._database_url

    @property
    def path(self) -> Path:
        """The SQLite file backing this store, resolved on first use.

        Nothing is created at construction — the URL is translated (and
        a URL this member cannot speak is refused by name) the first
        time an operation needs it.
        """
        if self._path is None:
            self._path = _sqlite_path(self._database_url)
        return self._path

    def _connect(self) -> sqlite3.Connection:
        """Open the database this store reads and writes.

        The caller owns the connection; use it as a context manager to
        commit, which is what :meth:`measure` does — the campaign
        probe, the row read and the ``INSERT`` are one unit of work, so
        a campaign planned by a concurrent process between the probe
        and the insert is seen, and two measurers of one campaign
        cannot interleave a read and a write.
        """
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _ensure_schema(self, connection: sqlite3.Connection) -> None:
        """Create this member's own table, idempotently.

        The one act that separates this store from
        :class:`providers.AgentModelPins`: that store writes a column a
        core migration owns and refuses to invent the table; this one's
        table is its own feature's record, on the ``bootstrap_world`` /
        ``depth_run_window`` precedent, and creating it lazily is the
        store's business.  ``IF NOT EXISTS``, so a database that
        already holds it — a second measurement, a restarted process —
        passes through untouched.
        """
        connection.execute(_SCHEMA)

    # -- Feature 200: the measurement ----------------------------------------

    def measure(
        self,
        campaign_id: Any,
        usages: Iterable,
        *,
        now: datetime | None = None,
    ) -> MeasuredCacheRate:
        """Measure one campaign's cache hit rate and persist it.

        Feature 200's sentence as one call: the campaign id and the
        calls' token accounting in, the stored measured rate out — the
        measurement and its persistence as one act, because a rate
        measured and not persisted is the sentence with its first half
        missing.  The steps, and why each is where it is:

        1. **Validate the ask** — the id as a UUID, the stream as
           feature 192's token accounting — before anything is opened,
           so a malformed ask is refused without touching a database.
        2. **Total the stream** (:func:`_measure_totals`) — the two
           counts the rate is the quotient of, computed from the
           usages rather than accepted as a caller's ratio, because
           *measured* is the sentence's own word.
        3. **Create the table**, lazily and idempotently — the row's
           first write brings its schema into being, and nothing else
           ever does.
        4. **Prove the campaign was planned** — the ``campaign`` table,
           probed read-only, holds a row with this id.  A rate measured
           for an id no campaign row holds is an accounting for calls
           that were never placed, and
           :class:`~providers.UnplannedCampaignError` is its refusal.
        5. **Return the stored row if the campaign is already
           measured** — an identical re-issue answers the row it finds
           (``recorded=False``, the original ``measured_at``, which a
           retry does not move) — or **refuse** when the fresh ask
           totals differently
           (:class:`~providers.CacheRateConflictError`, naming both
           totals and both rates).
        6. **Insert, then read back**, and return what the table holds:
           the counts and the instant are the row's, re-parsed through
           the same readers ``get`` uses, so a caller holds one record
           shape from one source of truth.

        Refuses, in this order, each naming what it is about: a
        malformed id or stream, a usage whose cache read exceeds its
        own input, a stream of no calls or of no input (the base
        :class:`~providers.DepthCacheError`); an unknown campaign
        (:class:`~providers.UnplannedCampaignError`); a re-measurement
        that totals differently
        (:class:`~providers.CacheRateConflictError`).
        """
        campaign = _validated_campaign_id(campaign_id)
        input_total, cache_total = _measure_totals(usages)
        # One instant for the row's stamp, computed once so the stored
        # value and any retry's comparison read the same moment — the
        # same "two clocks narrating one decision" guard
        # :meth:`providers.DepthRunWindows.schedule` states.
        measured_at = (
            _require_instant(datetime.now(UTC), "the measuring instant")
            if now is None
            else _require_instant(now, "the measuring instant")
        )
        with closing(self._connect()) as connection, connection:
            self._ensure_schema(connection)
            self._require_campaign(connection, campaign)
            stored = self._read_row(connection, campaign)
            if stored is not None:
                return self._reissued(stored, input_total, cache_total, campaign)
            connection.execute(
                f"INSERT INTO {DEPTH_CACHE_RATE_TABLE} "
                f"({CAMPAIGN_ID_COLUMN}, {INPUT_TOKENS_COLUMN}, "
                f"{CACHE_READ_TOKENS_COLUMN}, {MEASURED_AT_COLUMN}) "
                "VALUES (?, ?, ?, ?)",
                (
                    campaign,
                    input_total,
                    cache_total,
                    _format_instant(measured_at),
                ),
            )
            row = self._read_row(connection, campaign)
        if row is None:
            raise DepthCacheError(
                f"the cache rate measured for campaign {campaign!r} could "
                "not be read back after the insert; the row is the "
                "measurement, and a measurement that cannot be re-read is "
                "one this store cannot vouch for"
            )
        return self._record_from_row(row, recorded=True)

    def get(self, campaign_id: Any) -> MeasuredCacheRate | None:
        """One campaign's measured cache hit rate, or ``None`` when it holds none.

        ``None`` means *this campaign's calls were never accounted
        here* — nothing has measured it — which is the honest answer
        for a campaign no row holds, and the answer on a database whose
        ``depth_cache_rate`` table does not exist yet (a store that has
        never measured created nothing, and a read does not create
        it).  It does **not** mean the read failed: an unreachable
        database raises, so a caller can never mistake a broken store
        for an unmeasured campaign — the same distinction
        :meth:`providers.DepthRunWindows.get` draws.

        The record is **re-verified, not merely re-parsed**: the cache
        read never exceeds the input it is a portion of, the input is a
        positive integer, the instant parses — each refusal names the
        campaign, on the ground the read side is where corruption would
        otherwise be laundered, and a rate above 1.0 reading back as a
        measurement would be a campaign billed for more cache than it
        had prompt.  ``recorded`` is always ``False`` here: a read
        wrote nothing.
        """
        campaign = _validated_campaign_id(campaign_id)
        with closing(self._connect()) as connection:
            if (
                connection.execute(
                    _TABLE_EXISTS_SQL, (DEPTH_CACHE_RATE_TABLE,)
                ).fetchone()
                is None
            ):
                return None
            row = self._read_row(connection, campaign)
        if row is None:
            return None
        return self._record_from_row(row, recorded=False)

    # -- The words ----------------------------------------------------------

    def _read_row(
        self, connection: sqlite3.Connection, campaign: str
    ) -> tuple[Any, ...] | None:
        """One campaign's row as the table holds it, or ``None`` when absent.

        Selected column by column rather than with ``SELECT *``, the
        discipline :meth:`providers.DepthRunWindows._read_row` states:
        the order :meth:`_record_from_row` reads must be the order this
        names, and a column appended later must not silently shift the
        fields.
        """
        cursor = connection.execute(
            f"SELECT {CAMPAIGN_ID_COLUMN}, {INPUT_TOKENS_COLUMN}, "
            f"{CACHE_READ_TOKENS_COLUMN}, {MEASURED_AT_COLUMN} "
            f"FROM {DEPTH_CACHE_RATE_TABLE} WHERE {CAMPAIGN_ID_COLUMN} = ?",
            (campaign,),
        )
        try:
            return cursor.fetchone()
        finally:
            cursor.close()

    def _record_from_row(
        self, row: tuple[Any, ...], *, recorded: bool
    ) -> MeasuredCacheRate:
        """Build a :class:`MeasuredCacheRate` from a row, re-verified.

        The read path's one constructor, so :meth:`get` and
        :meth:`measure`'s read-back cannot disagree about which column
        is which.  Every value is re-parsed through the row-shaped
        readers (counts, the instant) rather than trusted — the
        record's own constructor then re-states the arithmetic laws, so
        a row that contradicts them is refused here, naming the
        campaign, which is the difference between an operator learning
        *this campaign's measurement is corrupt* and learning that some
        value somewhere does not parse.
        """
        campaign = _validated_campaign_id(row[0])
        return MeasuredCacheRate(
            campaign_id=campaign,
            input_tokens=_parse_count(
                row[1], campaign, INPUT_TOKENS_COLUMN, positive=True
            ),
            cache_read_tokens=_parse_count(
                row[2], campaign, CACHE_READ_TOKENS_COLUMN, positive=False
            ),
            measured_at=_parse_instant(row[3], campaign, MEASURED_AT_COLUMN),
            recorded=recorded,
        )

    def _reissued(
        self,
        row: tuple[Any, ...],
        input_total: int,
        cache_total: int,
        campaign: str,
    ) -> MeasuredCacheRate:
        """Answer a re-issued measurement: the stored record, or a conflict.

        The identical measurement — a fresh ask that totals the same
        two counts — returns the row the table holds, **including its
        original ``measured_at``**.  A retry is the same measurement
        arriving twice, and the row *is* the measurement: the retry did
        not move the moment it was taken, and the campaign's calls are
        what they are — the totals are re-derivable from the
        completions that served it and from nothing else.

        A fresh ask that totals **differently** is refused, and the
        refusal names both totals and both rates, because that is the
        difference between an actionable refusal and a complaint: the
        caller learns which measurement is stored and which its own
        ask computed.  The comparison is on the counts alone — they are
        the record, and the rate is their quotient, so two asks that
        agree on the counts agree on everything.
        """
        stored = self._record_from_row(row, recorded=False)
        if (
            stored.input_tokens == input_total
            and stored.cache_read_tokens == cache_total
        ):
            return stored
        raise CacheRateConflictError(
            f"campaign {campaign!r} is already measured at "
            f"{stored.cache_read_tokens:,}/{stored.input_tokens:,} "
            f"({stored.hit_rate.numerator:,}/{stored.hit_rate.denominator:,}"
            f" ≈ {float(stored.hit_rate):.4f}), and this ask would measure "
            f"it {cache_total:,}/{input_total:,}. One campaign is one run "
            "of the discovery loop, and its cache hit rate is a "
            "measurement of that run — the same campaign cannot have hit "
            "cache at two rates, so the stored row is the fact. Read it "
            "with get(), or plan the second run under its own campaign "
            "id so each measurement measures one run."
        )

    def _require_campaign(
        self, connection: sqlite3.Connection, campaign: str
    ) -> None:
        """Refuse to measure a campaign the campaign table does not hold.

        The store measures *a campaign's* calls, and a campaign is a
        planned row — feature 232's record, created before any node is
        expanded, is the row every reader of a campaign joins by id.
        The probe is read-only (``sqlite_master``, then one ``SELECT``
        by the table's own key), and the ``campaign`` table is **never
        created** here: it is ``0111``'s, and a store that invented it
        would be writing a schema it does not own.

        An **absent** ``campaign`` table is the same refusal as an
        absent row, not a different one: it is a database where no
        campaign has ever been planned, so the id necessarily names
        nothing.  The wording differs so an operator reading it learns
        which repair applies — run the migrations, or plan the
        campaign.
        """
        if (
            connection.execute(_TABLE_EXISTS_SQL, (CAMPAIGN_TABLE,)).fetchone()
            is None
        ):
            raise UnplannedCampaignError(
                f"the store at {self.path} holds no {CAMPAIGN_TABLE} "
                "table, so no campaign has ever been planned in it and "
                f"campaign {campaign!r} cannot have been either: a cache "
                "hit rate is measured for a campaign feature 232's "
                "planner recorded first. Run the migrations, plan the "
                "campaign, then measure its runs."
            )
        cursor = connection.execute(
            f"SELECT 1 FROM {CAMPAIGN_TABLE} "
            f"WHERE {CAMPAIGN_TABLE_ID_COLUMN} = ?",
            (campaign,),
        )
        try:
            found = cursor.fetchone()
        finally:
            cursor.close()
        if found is None:
            raise UnplannedCampaignError(
                f"there is no campaign {campaign!r} in the store at "
                f"{self.path}: a cache hit rate is measured for a "
                "campaign feature 232's planner recorded before any node "
                "was expanded, and an id the campaign table does not hold "
                "names calls that were never placed. Plan the campaign, "
                "then measure its runs."
            )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"{type(self).__name__}(database_url={self._database_url!r})"


def measure_cache_rate(
    campaign_id: Any,
    usages: Iterable,
    *,
    now: datetime | None = None,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
) -> MeasuredCacheRate:
    """Measure one campaign's cache hit rate — the module-level spelling.

    Feature 200's sentence as one call, for the caller that wants the
    act without holding a store: the campaign id and the calls' token
    accounting in, the stored measured rate out.  The store is resolved
    from ``database_url``, else from ``DATABASE_URL``; a deployment
    that names neither is refused *by name* rather than silently doing
    nothing, because a measurement that quietly skipped its write would
    leave the campaign's economics unaudited — and the next campaign's
    selection, justified by a rate nobody persisted, resting on a
    number that exists nowhere.

    A :class:`~providers.DepthCacheError` from the store is left to
    propagate unwrapped: the refusal already names the campaign and the
    fact, and re-wrapping it here would put a second message in front
    of the one an operator needs.
    """
    source = os.environ if env is None else env
    url = (
        database_url
        if database_url is not None
        else source.get(DATABASE_URL_ENV, "").strip()
    )
    if not url:
        raise DepthCacheError(
            "measure_cache_rate measures a campaign's cache hit rate and "
            f"nothing names a store: {DATABASE_URL_ENV} is unset (and no "
            "database_url was supplied), so the measured rate could not "
            "be recorded. Feature 200's record is a fact that must "
            "actually land in the table — a campaign whose measured rate "
            "was never persisted is one whose selection premise the next "
            "deployment has to take on faith, which is the article of "
            "faith this feature exists to replace."
        )
    return DepthCacheRates(url).measure(campaign_id, usages, now=now)
