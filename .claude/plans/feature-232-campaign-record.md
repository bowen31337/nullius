# Feature 232 — the campaign record, created before any node is expanded

app_spec.xml, "Discovery Orchestrator & Campaigns", feature 232:
*System creates a campaign record capturing type, workspace count and null
fraction before any node is expanded.*

Footprint: `packages/discovery/**`, `src/app/modules/discovery/**`.

## What already exists, and what this feature therefore is

`plugin="discovery"` under `<layout profile="uv-workspace"/>` resolves to
`packages/discovery/`, which **does not exist yet**. This is the member's first
feature, so the task is: stand up the member, and put feature 232 in it.

The `campaign` table already exists — `migrations/versions/0111_campaign_table.py`
(feature 104) creates it with `id, campaign_type, workspace_count, null_fraction,
calibration_status, ks_pvalue, created_at`. Seven other stores already
`CREATE TABLE IF NOT EXISTS campaign` idempotently and then *refuse to create
the row* (`nulloracle.phi`, `.flipdepth`, `.irprob`, `.ksguard`, `.verdict`,
`.plan`, `.selection`). `nulloracle/phi.py` says who does create it, in as many
words:

> ``null_fraction`` is fixed *before any node is expanded* … which is the
> planner's job (**feature 232's ``discovery`` plugin**), not this member's …
> a store that inserted the missing campaign would be inventing the row the type
> and the workspace count belong on.

So feature 232 is the missing writer those eight readers were built against.
No migration is needed (the table is 0111's, and `migrations/versions/**` is
core-task territory); no shared file is edited (the root `pyproject.toml`
already declares `members = ["packages/*"]`).

## Decisions

**1. A new workspace member `packages/discovery`, import name `discovery`.**
Stdlib-only (`sqlite3`, `urllib.parse`), `dependencies = ["nullius"]` for the
factory's `register` protocol — the shape `bootstrap` and `snapshot` ship.
Joins the workspace by convention; no registry/router/factory edit.

**2. The member never imports another member** (the workspace contract —
`packages/artifacts/tests/test_profiles.py` states it, `packages/sandbox/tests/
test_budget_law.py` demonstrates the remedy). Two spellings must therefore be
restated here and *pinned as data* by a cross-member test that imports the
sibling in-function, so a rename on the other side fails one test rather than
collection:

* §4.1.1's clip `φ = clip(2/W, 0.15, 0.35)` — restated as `PHI_FLOOR`,
  `PHI_CEILING` and `null_fraction(W)`, pinned against
  `nulloracle.null_fraction` / `nulloracle.PHI_FLOOR` / `nulloracle.PHI_CEILING`.
* §7.3's two regimes `"Type-R"` / `"Type-D"` — pinned against
  `nulloracle.plan.TYPE_R_CAMPAIGN_TYPE` / `TYPE_D_CAMPAIGN_TYPE`.

**3. Creation derives φ from W; the caller supplies type and W.** Feature 117's
docstring hands this member the act, and deriving keeps φ a fact about the
planned tree rather than a caller's guess. The clip is spelled once here (and
once in `nulloracle.phi`), which is why decision 2's pin exists — the pin is
what makes the second spelling safe.

**4. The ordering law is enforced by reading the tree, and it is checked
against `node`, never against a convention.** `create` refuses when the `node`
table already holds a row whose `campaign_id` is this campaign — i.e. the
record was *not* created before the first node was expanded. The `node` table is
**probed, not created**: this member does not own node's schema, and an absent
`node` table means nothing has been expanded, so the honest answer is "proceed"
(`sqlite_master` read-only probe, the `bootstrap/_census.py` idiom).

**5. Idempotent by campaign identity, because every store in this workspace
is.** Re-issuing the *identical* plan returns the stored record — including its
original `created_at`, since the row is the creation event and a retry does not
move it. A plan that *disagrees* with the stored row (`campaign_type` or
`workspace_count` differ) is refused: a campaign's declared type and workspace
count are fixed at planning time, and a second declaration naming different ones
would silently retype a world that was already planned (§7.3's homogeneity).

Note the node check runs on the **absent-row** path only. If the record exists,
the ordering law was satisfied (or violated) in the past; re-refusing a retry
would punish the retry without changing any fact.

**6. The check and the write are one unit of work** — one `with connection:`
transaction, the `phi.persist` shape — so a node expanded between the probe and
the INSERT cannot slip past.

**7. The returned record is read back from the table, not built from the
arguments**, so a caller gets the *stored* row: the minted id when none was
supplied (0111's `gen_random_uuid()`/`randomblob` default), the table's
`created_at`, `calibration_status = 'ok'` and `ks_pvalue IS NULL`. Those last two
are the seam features 123/124 read, and their being untouched is what "created
before the KS test ran" means.

**8. Error vocabulary — two classes under one base**, split by the caller's
repair, the `bootstrap/errors.py` discipline:

* `CampaignPlanningError` — *the ask was malformed*: an id that is not a UUID, a
  type that is neither of §7.3's two regimes, a `workspace_count` that is not a
  genuine positive integer (`bool` refused), a `null_fraction` row that is not a
  finite real strictly inside `(0, 1)`.
* `CampaignOrderError` — *the store's state contradicts the ordering law*: the
  campaign's tree already holds a node, or a re-creation disagrees with the
  stored row.

`DiscoveryError` is the base a caller catches for every failure of this path.

Why `(0, 1)` and not §4.1.1's band: the band is feature 117's and this member
must not re-spell it. The open interval is the minimal honest statement that φ
is *the fraction of the tree's wells that are null*, and both endpoints are
refused because §4.1.1's own premise is that a tree needs *at least two null
roots and two real roots* — a campaign that is all nulls or all reals measures
nothing. `clip` always lands in `[0.15, 0.35] ⊂ (0, 1)`, so the two never
disagree.

## Files

```
packages/discovery/pyproject.toml                  new member (bootstrap's shape)
packages/discovery/src/discovery/__init__.py       exports + @register("discovery")
packages/discovery/src/discovery/errors.py         DiscoveryError / 2 subclasses
packages/discovery/src/discovery/campaign.py       the clip, the regimes, the record, the store
packages/discovery/src/discovery/py.typed          (empty marker)
packages/discovery/tests/conftest.py               path bootstrap + per-test sqlite + vocabulary
packages/discovery/tests/test_campaign.py          the feature's own suite
packages/discovery/tests/test_cross_member.py      the two pinned spellings
packages/discovery/tests/test_component.py         registration, seat, second composition, degradation
src/app/modules/discovery/__init__.py              the seat: COMPONENT_NAME + campaign_records_component
```

`campaign.py` carries, on the `nulloracle.phi` pattern: `CAMPAIGN_TABLE`,
`NODE_TABLE`, the three campaign columns, `PHI_FLOOR`, `PHI_CEILING`, `REGIMES`,
`null_fraction(W)`, frozen `CampaignRecord` (validated in `__post_init__`, with
`.row()`), `CampaignRecords` (`resolve()`, `database_url`, lazy `path`,
`create(...)`, `get(...)`), and a module-level `create_campaign(...)` that
raises by name when nothing names a store. The component name is `"discovery"`
— the member's first component, so no prefix, the `ledger`/`artifacts`/`canary`
precedent. It sorts between `cost-model` and `evaluator`, leaving every
`nulloracle-*` adjacency assertion untouched.

## Verification

* `packages/discovery/tests` — the feature's own suite (inherits nothing from
  the repo root conftest, so it restates the sqlite isolation the way
  `packages/bootstrap/tests/conftest.py` does).
* `uv run pytest tests` — the acceptance gate's own collection, expected to stay
  green (nothing under `tests/` is touched).
* `uv run pytest packages/discovery/tests tests` — both, since the gate's
  `testpaths = tests` does not collect member suites.
* `ruff check` on the new files, compared against a sibling member (the repo's
  lint is red on `main`, so only my files are compared).
* `uv lock` — adding a member rewrites `uv.lock`; it is generated, additive, and
  what `bootstrap`'s own member-landing commit carried. Flagged because parallel
  tasks may add members concurrently.
