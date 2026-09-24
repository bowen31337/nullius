# Feature 305 — the final target weights, and the one output the orders read

**app_spec.xml, "Portfolio Book Construction", feature 305**
(`shape="plugin"`, `plugin="book"`, `depends_on="304"`): *System returns final
target weights as the only output consumed by the order layer.*

Declared file-claim scope: `src/app/modules/book/**`, `packages/book/**`.

## What the sentence means, and what it does not

Both documents state this fact at the foot of the construction's own chain, and
both state it as the chain's **last arrow** rather than as another step:

- `docs/alpha-engine-prd.md` §C8: *"Signal book → IR-weighted combination with
  shrinkage → volatility targeting → position and concentration limits →
  orders. Version-controlled, human-authored, explicitly outside the search
  space."*
- `docs/nullius-tech-architecture.md` §13.1: *"promoted signals → IR-weighted
  combine (Ledoit-Wolf shrinkage) → volatility targeting → position &
  concentration limits → target weights"* — the same chain named at its other
  end.

§13.2 (*"Execution engine"*) is the process on the far side of that seam and it
opens on `asyncio` + websockets, `exchangeInfo` filters and idempotent order
submission — none of which this member may touch.

**So the sentence adds no arithmetic, and that is the whole design.** Every act
it depends on already exists in the member: feature 301 combines (`_combine.py`),
feature 303 scales (`_volatility.py`), feature 304 bounds (`_limits.py`). What
the sentence states is a **shape** the construction's answer must have: one
value — the final target weights — is what the order layer consumes, and it is
the *only* thing it consumes.

**The tempting misreading — implement a "final weights" computation — is
refused by name.** Any re-normalization, re-scaling, re-ranking, rounding or
clamping here would be a second answer to a question 301, 303 or 304 already
answered, and the order layer would then hold a book that no bound had judged.
The sentence's *only* is precisely the rule against that.

**The second tempting misreading — an order-layer-facing artefact (a formatted
instruction, a `client_order_id`, a venue-rounding step) — is also refused.**
The router's own features own `LOT_SIZE`/`NOTIONAL`/`PRICE_FILTER` rounding and
the venue's filters (§13.2, features 310-313); this member publishes the book,
and the router is what turns it into orders.

## The decisions this feature takes

### 1. The act publishes; it never recomputes

`final_target_weights(target_weights)` takes the bounded book and answers a
frozen `FinalTargetWeights` carrying **the same floats** — read through
`_book_of`, the one reader the record's own `__post_init__` also uses, so a
hand-built record and a published one cannot be judged differently.
`FinalTargetWeights.weight(symbol)` returns the very figure feature 303 scaled
and feature 304 bounded.

### 2. The published record carries the book's own facts and nothing else

`weights`, plus two derived read-only figures:

- `symbols` — the symbols the instruction routes over, derived so it cannot
  disagree with `weights` (the discipline `TargetWeights.gross_exposure`
  states).
- `gross_exposure` — `Σ_s |w_s|`, the same number feature 303 exposes and
  feature 308's cap judges, answered here so a consumer of *this* record needs
  no second value.

The composite (301), the gross-normalized book, the scale and the two
volatility figures (303) and the limits the book was judged against (304) are
the construction's **working**. They stay on the record that computed them;
the sentence's *only* is what keeps them out of the order layer's instruction.

### 3. The *only* is readable over the whole surface, duck-typed

`is_only_output(published, *also_handed)` answers the sentence's fact and
`assert_only_output(...)` is its verdict. Both count values declaring
`kind == PUBLISHED_KIND`:

- the construction's **working is not contraband** — a caller may hold the
  composite, the scale and the target weights beside the published set, and
  those records are where those figures belong;
- a second **published set** is what the sentence forecloses, because two
  instructions leave the order layer choosing between them — the construction's
  own act performed one layer down with no bound re-run.

The gate is the value's own declaration, **not** `isinstance`. This is
load-bearing rather than stylistic: the module loader imports every member under
a synthetic name (`_nullius_scanned_book`), so a value composed in this process
may be a second class object that no `isinstance` here would recognise — the
same reason the chain's earlier steps read `scores` and `weights` off the
surface.

### 4. The predicate/verdict split follows feature 304's own

`is_only_output` answers the fact (``True``/``False``) and refuses **only** the
ask; `assert_only_output` raises the sentence's judgment. This mirrors
`is_breaching_limits` vs `rejects_breaching_target_weights` and
`is_missing_changelog_entry` vs `requires_changelog_entry`. A caller that
wants to *know* reads the bool; a caller that must be stopped before the venue
runs the verdict. Both settle the ask and count the declarations once, in
`_annexed`, so they cannot disagree.

### 5. `kind` is a `ClassVar`, not a field

`FinalTargetWeights` exposes `kind = PUBLISHED_KIND` as a class constant.
Verified: `FinalTargetWeights(weights={...}, kind='other')` raises `TypeError`
and `f.kind = 'other'` raises `FrozenInstanceError`. So a record cannot be built
that declares itself something else and then slips through the seam's own gate —
the declaration is not a parameter a caller can set. `consumed_by_order_layer()`
consequently answers `True` unconditionally, which is honest: a value that is not
this one never becomes a `FinalTargetWeights` at all.

### 6. Absence is not zero, on the chain's last step

Refused as `FinalWeightsRequestError` (opening with `NO_BOOK_CODE`, `no_book`):
a value carrying no `weights`, a non-mapping, a set covering no symbols, a blank
symbol name, a weight that is not a finite real, and a value meant for the
orders that declares itself no published book.

**Answered**: a book held flat — every weight `0.0`, which is exactly feature
303's zero-target answer and which feature 304 admits at every limit of zero or
more. *Hold nothing* is an instruction the construction is entitled to publish,
where no book at all is not. The two zeros this member distinguishes one step
upstream are distinguished here too, read on the published set.

### 7. Two classes, siblings under the member's one base

- `FinalWeightsRequestError` — the ask's own facts. Carries `no_book` where what
  was handed over is not a book; carries no code where a real book was badly
  keyed or badly valued, the reason `LimitRequestError` gives (a malformed key
  names its subject in its first words).
- `OrderLayerOutputError` — the one judgment the sentence mints, carrying
  `annexed_record` and naming every annexed record.

They are siblings of `BookConstructionError` rather than of each other, because
the caller's position differs: the first is an ask that named no book, the
second is a real book in a malformed instruction — the test feature 304 states
for its own two codes, read the other way.

### 8. No new component, and the layering bill

`_publish.py` imports `collections`, `dataclasses`, `math`, `types`, `typing`
and the member's own `.errors`, and nothing else. No `@register`, no table, no
endpoint, no migration, no seat edit. `__init__.py` widens its re-export and
`__all__` and gains no logic; the seat (`src/app/modules/book`) is unchanged and
still re-exports nothing. `create_app()` still carries exactly one `book`
component. Verified after the change: `app.order` contains one `book` and no
`publish`.

The publication takes no figure of its own — the chain's earlier steps carry
every number (303's configured volatility, 304's two limits) and each reaches
its *own* call — so `final_target_weights` has no configurable keyword and
`build_book_combiner` still takes no arguments.

## Files

- `packages/book/src/book/_publish.py` (new) — `NO_BOOK_CODE`,
  `ANNEXED_RECORD_CODE`, `PUBLISHED_KIND`, `_MISSING`, `_book_of`,
  `FinalTargetWeights`, `final_target_weights`, `_asserts_final_target_weights`,
  `_annexed`, `is_only_output`, `assert_only_output`.
- `packages/book/src/book/errors.py` — `FinalWeightsRequestError` and
  `OrderLayerOutputError` added as siblings; `__all__`, the module docstring's
  feature and code lists and the base class's docstring widened.
- `packages/book/src/book/__init__.py` — re-export and `__all__` widened; the
  package docstring states the member now carries seven features.
- `packages/book/tests/test_publish.py` (new) — 33 claims: publication without
  recomputation, the record's fields and derived figures, the *only* over the
  whole surface, the duck-typed declaration, the ask/judgment split, absence vs
  the flat book, the vocabulary, the end-to-end chain, and the layering pins
  (stdlib-only from the AST, no other member imported, no store/environment/
  clock).
- `packages/book/tests/test_component.py` — the surface pin widened to the
  seven features and feature 305's composition story added.

## Verification

- `uv run --frozen pytest packages/book/tests` — **397 passed** (was 363).
- `uv run --frozen pytest` (repo-level acceptance suite) — green.
- `uv run --frozen ruff check packages/book/` — all checks passed.
- `create_app()` inspected directly: exactly one `book` component, no `publish`.
- No file outside the declared footprint was modified (`git status`).
