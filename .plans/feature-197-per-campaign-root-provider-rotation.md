# Feature 197 — the per-campaign root provider rotation, persisted

**Spec sentence.** *System persists a per-campaign root provider rotation, so
different model families propose structurally different mechanisms.*

**Shape.** plugin, member `providers`, `depends_on=196`.

**Files.** `packages/providers/src/providers/_rotation.py` (feature 197's
module), `_rotation_errors.py` (its error vocabulary), `__init__.py` (import
block, `__all__`, one constant, one builder), `src/app/modules/providers/__init__.py`
(seat widened by one name and one accessor), `packages/providers/tests/conftest.py`
(a feature-197 fixture section), `test_rotation.py`, `test_rotation_component.py`,
and the two seat assertions in `test_pin_component.py` / `test_served.py`
widened by this feature's pair.

---

## The architecture law

`docs/nullius-tech-architecture.md` §14.1, the paragraph under the role table:

> **Rotating providers at roots is the cheapest mitigation available** for the
> convergence failure mode. Different model families carry different priors and
> propose structurally different mechanisms, at zero incremental token cost, and
> it hedges outages.

§14.2's roots row names the members and states the instruction:

> `claude-opus-5` … `gpt-5.6-sol` … `gemini-3.1-pro` — *"Rotate all three.
> Different families, different priors, different mechanisms proposed."*

`docs/alpha-engine-prd.md` §409 states the same split from the PRD's side:
*"Roots get a frontier model rotated across providers."* §14.1 supplies the
sentence that keeps the model names out of this module — *"rates move monthly …
the selection logic is stable, the numbers are not"* — and the provenance
failure (`deepseek-v4-flash` retired 2026-09-10 while still accepting the ID)
that makes *which* provider served a root a fact worth persisting.

## Where this sits relative to its siblings

| feature | its fact |
| --- | --- |
| 192 | the completion seam: one normalized answer, and *who served it* is **reported** |
| **196** | **records which provider served each root call** — *what served* |
| **197** | **persists the per-campaign rotation** — *what was assigned* |
| 201 | routes a depth call to an endpoint; persists nothing |
| 202 | schedules a depth run and persists the window **with its premise** (the card) |
| 215 | measures the realized diversity (`tree_diversity`) |
| 203 | pins `node.agent_model_id` — which model authored this node |

Feature 196's module docstring draws this feature's half of the seam in as many
words: *"It does not choose the rotation. Which of the declared providers serves
this root call is feature 197's question … 196 persists what served, 197
persists what was assigned, and a store that did both would be deciding an
assignment on the way to writing it down."* 197 is the other half: the
per-campaign assignment that 196's per-call row then records.

## The design

**D1 — an eighth error base, `RootRotationError`.** The taxonomy splits by
*question*. The seven existing bases answer: a call failed (192), a pin is
unreadable (203), a depth model was refused (198/199), a window could not be
found (202), an endpoint went unchosen (201), a rate was never measured (200),
a root call's serving provider could not be recorded (**196**). None answers
*which family was this campaign's root assigned to, and is this provider one of
them?* — the **assignment** question, which is asked one layer above the record
question. Under `RootProviderError` would be wrong: a caller catching 196's base
must not have an *assignment* refusal answered in its place, and the two repairs
differ (declare the rotation, versus serve the call from a family that is in
it). Also raised directly for the malformations no subclass describes,
per the module-docstring ground every taxonomy in this package states.

**D2 — the structural difference is decided, the record is 196's.**
`RootRotation.assign` calls feature 196's `RootProviderRotation.record`, so the
row lands in `root_serving_provider` through one writer and one gate — the node
must be the tree's and a root, the campaign and depth must match, the serving
family must be declared. 197 adds the *decision* that gate needs (which family
serves this root) plus the per-campaign rotation record that decision belongs
to; it does **not** write a second provenance column. The two sentences are
*what was assigned* and *what served*, and this module is the first.

**D3 — the assignment is a pure function of the root's identity.**
`index = H(campaign_id ‖ node_id) mod n` over the tier's canonical member order
(`FrontierTier` already sorts by `(provider, model)`), so:

* **exactly one family per root**, and the index is the same on every path —
  a retry, a resumed campaign, a re-derivation by an auditor, a second process;
* **stable under reordering**: the family does not depend on the order the loop
  happens to expand roots in, so two runs that place the same roots in a
  different order write the same rows. Positional round-robin is rejected for
  exactly this reason — it makes the assignment a property of an enumeration
  rather than of the root.
* **family-invariant**: the arithmetic reads only the two ids and the *size* of
  the set; the families' own names enter through the canonical order alone, and
  the digest (D6) is blind to them.

What it deliberately does **not** promise is a count. §14.1's goal is that the
campaign's roots *span* families; a hash draws a multinomial over the slots, not
a 1:1 allocation, and a campaign of three roots may draw the same family twice.
That is a real and stated limit, not an oversight: the system reaches for exact
allocation where a *count* must be right (feature 236's largest-remainder
allocator over `Fraction`s, in the discovery member, for the depth budget), and
this feature's fact is not a count — it is one root's family. The realized
diversity is what feature 215's `tree_diversity` measures, per authoring model,
and 197 announces no figure.

**D4 — the rotation row-set is the per-campaign record, and it is the
rotation.** `root_provider_rotation`, one row per `(campaign_id, node_id)`,
created lazily by the store's first `assign` (`CREATE TABLE IF NOT EXISTS`) —
the `bootstrap_world` / `depth_run_window` / `depth_cache_rate` /
`root_serving_provider` precedent, a member-owned table for a member-owned fact,
no edit to the shared migration chain. `campaign_id` is the key's left half, so
one campaign's rotation is one indexed read; the row-set **is** the rotation,
and the store is append-only per `(campaign, root)`.

**D5 — the premise is persisted on this feature's rows (this is where 196's D6
said it would live).** Each row carries the declared member set as canonical
JSON beside the digest. 196 refused to carry the tier on *its* row because the
tier is 197's per-campaign fact, written down once and read by campaign id;
this table is that record, and the premise is repeated per row so a rotation is
readable row by row without a join, and so the one drift check (*does any row of
this campaign carry a different declared set than the one being declared now?*)
is a single comparison rather than a second table. A row-set declared two ways
is refused by the base error, naming both sets.

**D6 — `rotation_digest`: the campaign's rotation as one identifier.**
`sha256(campaign_id ‖ canonical tier text)`, hex, carried on every row. It is
what feature 214's `campaign_discrimination` is keyed by — *"two campaigns per
candidate model"* means the loader pins the model to reproduce the campaign, and
the digest makes "the rotation was the same" / "the rotation differed" a string
comparison rather than a re-derivation. It is deliberately **blind to the family
names**: swapping one family's member changes the canonical text (the order
changes) and the digest, while changing a *marker* would not — there is no
marker, because the assignment function has none.

**D7 — the record is closed by `record_root_provider`, 196's gate plus 197's.**
`RootRotation.record_root_provider(call, serving)` is the pair: the rotation
must **cover** the call — a row for `(call.campaign_id, call.node_id)` must
exist and must name `serving` — and then 196's `record` lands the provenance
row. An assigned root call served from a family the rotation does not cover is
`UnassignedRootProviderError` (197's sibling of 196's
`UnknownRootProviderError`: *the declared set does not name it* versus *the
assigned rows do not cover it*), refused **before** any row is written, because
that is the state a silent re-route would otherwise write itself into, which is
§14.1's documented failure verbatim.

**D8 — recognition by parts, answers re-made.** Everything crossing the seam
(the campaign's declared tier, the serving member, the root call) is recognised
through its parts and re-made from this module's classes — the double-import
remedy every seam in this package makes; the tier through 196's own parts tuple,
by asking for the `providers` attribute and handing it to `FrontierTier`.

**D9 — refusals the store makes and the ones it does not translate.** 197's own
gate raises `RootRotationError`, `UnassignedRootProviderError` and
`RotationConflictError`. Feature 196's gate — called inside `assign` — raises
its own vocabulary (`RootNotRecordedError` for a node the tree does not hold,
`UnrotatedCampaignError` for a call below the root tier, the base for a
declaration the tree contradicts, `RootProviderConflictError` for a provenance
row that names another family). Those are left to propagate **untranslated** and
are pinned by the suite: each already names the fact precisely (the node, the
depth, the tree), and re-wrapping them in 197's vocabulary would put a second,
vaguer message in front of the one an operator needs.

## Files

| file | change |
| --- | --- |
| `packages/providers/src/providers/_rotation.py` | new — the module |
| `packages/providers/src/providers/_rotation_errors.py` | new — the eighth base + 2 subclasses |
| `packages/providers/src/providers/__init__.py` | import block, `__all__`, `ROOT_ROTATION_COMPONENT`, `build_root_rotation`, docstring |
| `src/app/modules/providers/__init__.py` | `ROOT_ROTATION_NAME`, `root_rotation_component`, docstring (four → five services, five → six registrations) |
| `packages/providers/tests/conftest.py` | feature-197 section: `root_rotation`, reuse of `tree_database` / `root_call` / `frontier_tier` |
| `packages/providers/tests/test_rotation.py` | new |
| `packages/providers/tests/test_rotation_component.py` | new |
| `packages/providers/tests/test_pin_component.py` | seat `__all__` widened (8 → 10) |
| `packages/providers/tests/test_served.py` | seat `__all__` widened; the member's registrations five → six |

## Tests

`test_rotation.py` — the arithmetic (determinism, one family per root, the same
root in two campaigns, all three families reachable across a campaign's roots,
a tier of one assigning its only member, a foreign-copy tier, the modulus over a
stripped/canonical id); the gate (an undeclared serving family refused before
any row is written, a call below the root tier, a node the tree does not hold,
an empty/duplicate tier, a malformed id); the record (the row-set, the digest's
blindness to family names and its sensitivity to the declared set, the premise
JSON, the idempotent re-issue answering the stored row and leaving one row, the
conflict naming both families, a tier drift refused naming both sets, two roots
of one campaign as two rows, the read-back re-verification); the pair
(`record_root_provider` closing the rotation, the serving family the rotation
does not cover, the provenance row landing in 196's table through 196's gate,
196's refusals propagating untranslated); construction (`resolve` with
unset/blank/set, no I/O at construction, non-sqlite refused, `:memory:` refused,
blank URL refused); the free function (lands the rows, reads the environment,
refuses by name when nothing names a store).

`test_rotation_component.py` — registration under its own name; composition by
scan; a second composition still holds it (the submodule-registration trap, now
on the member's sixth registration); the builder answering `None` with no
`DATABASE_URL` and a bound store with one, creating nothing; the builder taking
no arguments; the seat's name pinned against the member's; the accessor reading
the application it is handed; the composed copy's vocabulary asserted by class
*name*.

## Verification

- `uv run pytest packages/providers/tests` — **792 passed** (2:13). Feature
  197's own two files are 82 + 12 of them.
- `uv run pytest` (the acceptance gate's own collection) — **1060 passed**
  (5:10), the baseline held.
- Both run as separate commands; same-basename files collide under one pytest.
- `uv run pytest -q` collects only `tests/` (pytest.ini `testpaths`), so the
  member suite above is *not* graded by the gate — it is run explicitly, and
  the member's own `packages/providers/tests` is where this feature's suites
  live.
- Lint only the new/changed files against a sibling: `ruff check` on the new
  module, the error module, the two suites and the touched `__init__` / seat /
  conftest files is clean, which is the comparison that matters (the repo
  baseline is red on main for unrelated files).
- `uv sync --all-packages` was needed before the gate could collect at all:
  `polars` / `pyarrow` are absent from a bare sync and two contract suites
  fail at import without them.

## Explicitly out of scope

- Which provider *served* a root call — feature 196's row, written through
  feature 196's gate.
- The realized diversity metric — feature 215's `tree_diversity`.
- Any model name, price or window as a module default — §14.2's numbers move.
- A count-per-family guarantee — D3, and feature 236's allocator is the sibling
  mechanism the system uses where a count must be exact.
- Editing 196's gate, table or vocabulary: this feature composes it.
