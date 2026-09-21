# Feature 241 — the configured legal theme set, refused at assignment

app_spec.xml, "Discovery Orchestrator & Campaigns", feature 241:
*System rejects a root theme outside the configured legal set when assigning
a research theme.* `plugin="discovery"`, `depends_on="232"`.

Footprint: `packages/discovery/**`, `src/app/modules/discovery/**`.

## What already exists, and what this feature therefore is

`packages/discovery` exists (feature 232 landed it: the campaign record, the
store, the `discovery` component and its app seat). Feature 241 is the member's
second feature, and it is a *refusal* on the assignment path, not a store.

The vocabulary it is about already exists in the workspace:

* `node.theme_root TEXT NOT NULL` — `migrations/versions/0118_node_table.py`
  (feature 97), which describes the column as *"the research theme this node's
  root was planted in, the axis the overfit signature is measured against"*.
  The column carries **no** `CHECK`: the legal set is *configuration* and
  changes per deployment while the schema is fixed, so the refusal has to live
  in the orchestrator's assignment path.
* The legal set itself is the human's input:
  `docs/alpha-engine-prd.md` §9.3 lists the initial six theme roots, and §9
  says outright — *"Choosing the space is the highest-value human input in the
  system, and it should be encoded as the set of legal `theme_root` values."*
* `illegal_theme` is the spec's own word for this refusal (feature 212 names
  the message), and §7.1's `is_null_column` / §7.3's `heterogeneous_world`
  refusals show the house convention: the message begins with the code.

## Decisions

**1. The legal set is configuration, so there is no component and no seat.**
The factory's registration protocol exists for *state a deployment holds* — a
store, a device, a materialised pool. A set resolved from a variable is not
that: it opens nothing, writes nothing and holds no state, and a component
whose builder can never return `None` (the PRD default applies when nothing is
configured) would be a function wearing a component's name. `ThemeSet` is a
value and `assign_theme` is a verb; the member's first component stays the
campaign store, and feature 232's component suite — which asserts the member
registers exactly one unprefixed name — is untouched.

**2. The initial set is PRD §9.3's six, as canonical slugs, and it is the
default.** Unset `NULLIUS_LEGAL_THEMES` means *the initial set*, not *no
constraint*: an unconfigured deployment still has a space (canary's
`allowlist_from_env` stance — *"a deployment that declared nothing still has a
ceiling"*). Set-and-blank is the strictest space — nothing legal — which is a
stance, not a gap, and the refusal names it.

| PRD §9.3 | slug |
|---|---|
| Cross-sectional momentum and short-term reversal, small/mid-cap universe | `cross-sectional-momentum` |
| Order-flow imbalance and microstructure features from the free L2 feed | `order-flow-imbalance` |
| Borrow-rate and funding-state conditioning | `borrow-rate-conditioning` |
| Volatility-state and dispersion regimes | `volatility-dispersion` |
| Mechanical calendar and event effects | `calendar-events` |
| Cross-asset and cross-venue state divergence (state, not price) | `cross-asset-divergence` |

**3. Case is insignificant; punctuation is not.** A theme identifier is a
lowercase slug (`^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$`). `assign` strips and
casefolds — `" Momentum "` is the same theme as `"momentum"`, and the canonical
form is what a caller banks, so the family key feature 228 conditions on cannot
split in two. A spelling that is one keystroke away but *different*
(`order_flow_imbalance`, `order flow imbalance`) is refused rather than
guessed at — the same refusal-not-normalisation stance feature 232's
`_validated_campaign_type` states for §7.3's regimes.

**4. Membership is checked at assignment, and the check is one call.**
`ThemeSet.assign(theme) -> canonical | raise IllegalThemeError`, plus
`is_legal` / `__contains__` for the question and `assign_all` for the multi-root
act a campaign always is (PRD §11.1 requires ≥3 distinct roots). A batch
refuses *collectively*, naming every offender, the style
`canary.screen_imports` uses — a planner that learned one bad root per attempt
would be replanned to learn the rest. `assign_all` takes an **ordered
sequence** and refuses a string, a mapping or an unordered set by name: all
three iterate, so all three would be silently read as a batch (a string's
characters, a mapping's keys, a set's hash-seeded order) and could report
success for assignments nobody made.

**5. One error class, under the member's base.** `IllegalThemeError(DiscoveryError)`
carries both faces of the refusal — a *configured* term that is not a theme
identifier, and an *assigned* theme outside the configured set — because both
answer the same question (*can this value be a legal theme here?*) and canary
folds its two the same way. A sibling of `CampaignPlanningError` rather than a
subclass: an illegal theme is a fact about the deployment's configured space
(a human's input, PRD §9), while a bad `W` is a fact about the loop's own
request — different repairs, and a caller wanting the broad bucket catches
`DiscoveryError`.

**6. Boundaries, stated so they are not re-implemented here.** Feature 213's
structurally-dead-territory refusal and feature 212's proposal-level twin are
the signal-agent member's; feature 234's ≥3-distinct-roots check is the
planning path's, at planning time; feature 218's `legal_roots()` is the
policy-facing runtime's. This module owns one fact — *is this theme in the
configured legal set?* — and the verb that refuses the assignment when it is
not.

## Files

```
packages/discovery/src/discovery/themes.py       new: the set, the resolver, the verb
packages/discovery/src/discovery/errors.py       + IllegalThemeError
packages/discovery/src/discovery/__init__.py     + exports (additive)
packages/discovery/tests/test_themes.py          the feature's own suite
```

No migration (`node`'s schema is 0118's), no shared file, no new member, no
`uv.lock` change.

## Verification

* `uv run pytest packages/discovery/tests` — **224 passed** (138 from feature
  232, unchanged, plus 86 new).
* `uv run pytest tests` — **1060 passed** (the acceptance gate's own
  collection; needs `uv sync --all-packages` first — repo test env gap).
* `ruff check packages/discovery/` — clean.

Two defects were found by the pre-exit checklist and fixed here, both the same
shape — *one value silently read as several*:

* `assign_all("abc")` over a space of `{"a", "b", "c"}` returned a successful
  three-theme batch: a single-letter theme is a legal identifier, so a
  mistyped theme became a grid and feature 234's distinctness law would have
  been checked against themes nobody assigned. Now refused by name.
* `assign_all(None)` raised a bare `TypeError` out of the feature's own verb —
  a Python exception name rather than a refusal naming the value. Now an
  `IllegalThemeError`.

Checking the fix for the second surfaced a third case of the first:
`assign_all` is `Iterable`-based, so a *mapping* had its keys iterated and an
unordered *set* was accepted in hash-seeded order. The guard is now "ordered
sequence", which covers all three.
