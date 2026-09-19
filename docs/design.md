# NULLIUS — Interface Design

**Version:** 0.1
**Companion to:** `alpha-engine-prd.md`, `nullius-tech-architecture.md`
**Audience:** one expert operator, daily, for years.

---

## 1. The design thesis

NULLIUS measures its own false discovery rate. The architecture doc states the consequence bluntly: if the primary chart is an equity curve, the system's actual purpose has been quietly abandoned.

**So the information hierarchy is the product thesis made visible.** Every layout decision below follows from one question: does this make epistemic state legible, or does it make money legible? The first is the job. The second is a tertiary panel two clicks deep.

Three things the interface must make impossible to get wrong:

1. **Mistaking an in-sample number for a confirmed one.** Solved typographically, not with badges (§4).
2. **Comparing two numbers produced by different evaluators.** Solved with a provenance chip (§5.2).
3. **Forgetting that sequestered data is finite and depleting.** Solved by putting the gauge in permanent chrome (§5.3).

---

## 2. Visual vernacular: the assay plate

The subject matter supplies the metaphor, and it is not a metaphor so much as a literal description. NULLIUS runs a plate with hidden control wells. You cannot tell the controls from the samples until you read the plate. That is exactly what a microplate reader does, and laboratory instrumentation is therefore the correct vernacular — not fintech, not a trading terminal.

What follows from that:

- **Wells, not cards.** Campaign nodes render as a dense uniform grid. Uniformity is the point: a control well must look identical to a sample well.
- **Blinded by default, read as a deliberate act.** Native to the metaphor rather than bolted on (§7).
- **Measurement rendered as density, not hue.** Instruments encode magnitude as intensity along one ramp. Categorical color is reserved for epistemic state.
- **Panels are lighter than the page.** The working surface sits above the bench, inverting the usual dark-panel-on-light-page convention. Small move, immediately distinctive.

### Explicitly rejected

| Rejected | Why |
|---|---|
| Green-up / red-down | Imports the P&L instinct into a system whose whole claim is that P&L is the wrong primary signal |
| Equity curve above the fold | See §1 |
| Glassmorphism, neon on navy | The crypto-trading aesthetic signals "get rich," which is the opposite of this product |
| Rounded cards with soft grey shadows | Identical containers flatten a hierarchy that is not flat |
| ALL-CAPS eyebrow labels, meta strings joined by middle dots | Chrome that appears regardless of subject |
| Monospace for small text *labels* | Cliché. Monospace for *numerals* is functionally required (tabular alignment) and kept |
| Total return in the navigation | There is no screen where that is the question being asked |

---

## 3. Tokens

### 3.1 Color

The palette is built on an epistemic axis, not a financial one.

```css
--ground:      #E9EAE4;   /* bench laminate — pale sage-grey, not cream */
--plate:       #F4F5F1;   /* working surface, sits ABOVE the ground */
--recess:      #DDDFD8;   /* inset wells, empty states */

--ink:         #16211C;   /* deep green-black — reads as ink, not tinted black */
--graphite:    #5C6661;   /* secondary text, provisional numerals */
--hairline:    #C6C9C0;   /* 0.5px rules */

--confirmed:   #1F5C4A;   /* viridian — verified out-of-sample */
--provisional: #A8712A;   /* ochre — in-sample only, unconfirmed */
--void:        #7A3040;   /* oxblood — instrument untrustworthy */
--control:     #3C4A8C;   /* indigo — revealed control well (read mode only) */
```

**Two rules that keep the semantics clean:**

1. **P&L numerals render in `--ink`. Always.** Never viridian, never oxblood. The epistemic colors mean *how much do we trust this*, and letting them touch money would silently restore the good/bad mapping this palette exists to avoid.
2. **`--void` is somber, not alarming.** A failed KS guard or a drifted canary means the instrument is offline, not that you lost money. Oxblood reads as quarantine; a bright red would read as a crash.

Dark mode inverts `ground`/`plate`/`ink` and lifts the three state colors by roughly 25% lightness. It is not the default: this interface is used under office light against printed notes.

### 3.2 Type

```css
--font-ui:   "Instrument Sans", system-ui, sans-serif;   /* prose, labels, chrome */
--font-num:  "Sometype Mono", ui-monospace, monospace;   /* every numeral, no exceptions */
```

Two families, clearly distinct. Instrument Sans is a neo-grotesque with enough quirk to avoid reading as a default UI font. Sometype Mono has a typewriter warmth that keeps dense tables from feeling like a terminal dump, and it has true tabular figures, which is non-negotiable because these numbers are compared vertically all day.

Scale, 1.25 modular from a 14px base:

| Token | Size / line-height | Use |
|---|---|---|
| `--t-micro` | 11 / 1.4 | Chip labels only. Used sparingly |
| `--t-base` | 14 / 1.5 | Body, table cells |
| `--t-lead` | 17 / 1.5 | Section intros |
| `--t-head` | 21 / 1.3 | Panel headings |
| `--t-title` | 26 / 1.2 | Screen title |
| `--t-readout` | 56 / 1.0 | The single hero numeral. One per screen, maximum |

Weights: 400 and 500 only. No 600, no 700. Emphasis comes from color and the confidence treatment, not from weight.

Prose caps at 68 characters. Sentence case everywhere, including chips.

### 3.3 Space and shape

4px base grid: `4, 8, 12, 16, 24, 32, 48`.

```css
--r-well:   2px;   /* wells and chips */
--r-panel:  3px;   /* panels, inputs, buttons */
```

Low radius because instruments are not soft, but deliberately not zero — zero radius plus hairline rules is the broadsheet default and it appears on every brief. 2px and 3px is a choice.

Rules are `0.5px solid var(--hairline)`. No shadows anywhere. Elevation is expressed by surface lightness (`--plate` above `--ground`), which is how a physical bench works.

---

## 4. The confidence treatment

**The one place boldness is spent.** Everything else is quiet.

Epistemic provenance is encoded in the rendering of the numeral itself, so a number cannot be misread even glanced at sideways, and the treatment survives screenshots pasted into notes.

| State | Treatment | Meaning |
|---|---|---|
| **Confirmed** | `--ink`, weight 500, no ornament | Measured on sequestered or forward data |
| **Provisional** | `--graphite`, weight 400, 0.5px dotted underline | In-sample only. Not yet confirmed |
| **Projected** | `--graphite`, weight 400, italic | Modelled or extrapolated, never measured |
| **Void** | `--void`, 0.5px strikethrough | Produced under a failed guard. Do not use |

```html
<span class="num num--provisional">1.47</span>
<span class="num num--confirmed">0.82</span>
<span class="num num--void">2.13</span>
```

Rendering a numeral without a state class is a lint error. There is no neutral default, because "I didn't think about where this number came from" is precisely the failure mode the treatment exists to prevent.

The dotted underline is the workhorse. It is quiet enough to sit in a dense table without shouting, and unmistakable once you know it. After a week it becomes preattentive: you stop reading provisional numbers as claims.

---

## 5. Components

### 5.1 Well

The atom. A square, `20×20` at default density, `14×14` compressed.

- **Fill** encodes magnitude along a single-hue density ramp from `--recess` to `--ink`. Not a diverging scale, not a rainbow.
- **Unrevealed** wells are `--recess` with no border.
- **Revealed** wells gain a 0.5px `--hairline` border.
- **Pruned** wells drop to 30% opacity and keep their fill, so a pruned branch reads as history rather than absence.
- **Control wells** are visually identical to sample wells in blinded mode. This is a hard requirement, not a style preference (§7).

### 5.2 Provenance chip

Three 3×10px segments, colors derived deterministically from the first bytes of `evaluator_hash`, `snapshot_hash`, `cost_model_hash`.

```
▌▌▌  1.47
```

Two numbers with different chips are not comparable, and you see it without reading a single hex character. On hover, the full triple. Chips appear on every score in every table. They cost 12px and they prevent the most expensive category of silent error in the whole system.

### 5.3 Epoch gauge

Sequestered epochs are non-renewable and retire after three promotion decisions. When they run out, the system stops, and that is a designed terminal state rather than a bug.

Rendered as a row of discrete marks, punched out as consumed — a dosimeter badge, not a progress bar. A bar implies a task completing; this is a resource depleting, and the difference matters.

```
epochs   ■■■□□□□  4 of 7 clean
```

Permanent in the left rail. At two remaining it shifts to `--provisional`. At zero the rail shows the terminal state with a plain line of copy: *No clean epochs remain. Promotion is blocked until new market data seals.* No modal, no alarm.

### 5.4 Instrument status

Three binary lamps at the top of the left rail, because everything below them is worthless if any is out:

```
canary     ok        replay is deterministic
ks guard   ok        nulls indistinguishable
ingest     1.2s      feed lag
```

Any failure turns the rail `--void` and stamps every numeral rendered during the affected window with the void treatment, retroactively. Bad data does not quietly age into good data.

### 5.5 Density toggle

`Comfortable` / `Compressed`. Compressed drops well size to 14px, row height to 24px, and hides prose descriptions. This tool is used by one person every day; let them decide how tight it gets.

---

## 6. Layout

Fixed left rail, fluid main column, inspector on selection. Left-aligned throughout. Nothing is centered, because centered content wastes horizontal space that dense tables need.

```
┌────────────┬──────────────────────────────────────┬───────────────┐
│ NULLIUS    │  Bench                               │               │
│            │                                      │   inspector   │
│ canary  ok │  ┌────────────────┐  FDR deploy      │   (on select) │
│ ks      ok │  │ ▪▪▫▪▫▫▪▪▫▪▫▫▫▫ │                  │               │
│ ingest 1.2s│  │ ▪▫▪▪▫▪▫▫▪▫▫▫▫▫ │      0.23        │   node id     │
│            │  │ ▫▪▫▫▪▫▫▫▫▫▫▫▫▫ │   ▌▌▌ π₀ = 0.90  │   ir marginal │
│ epochs     │  │ ▫▫▫▫▫▫▫▫▫▫▫▫▫▫ │                  │   turnover    │
│ ■■■□□□□    │  └────────────────┘  sens 0.71       │   decay       │
│            │   campaign 24 · blinded  spec 0.94   │   code ▸      │
│ Bench      │                                      │               │
│ Campaign   │  ─────────────────────────────────── │               │
│ Dreaming   │  Pool          52 worlds  ▪ 38 fin   │               │
│ Book       │  Revisions     M = 40                │               │
│ Ledger     │  Holdout ΔIR   0.34  p = 0.011       │               │
└────────────┴──────────────────────────────────────┴───────────────┘
```

The hero is the live plate beside a single large `FDR_deploy` numeral. Not a big number with a gradient accent — the plate is the characteristic object in this system's world, and the number is meaningless without it.

Below the fold: pool size, revision count, holdout result. The things that decide whether the number above is trustworthy.

---

## 7. Blinded and read modes

The information barrier is an interface constraint, not only a backend one. `is_null` must not be visually inferable by anyone operating a live campaign, including by accident.

**Blinded** is the default and covers every live campaign.

- Control and sample wells are pixel-identical.
- No sort, filter, or group control can partition by anything derived from null status.
- The inspector shows no field that would narrow it.

**Read** is retrospective only, available after a campaign closes, and reached through an explicit action labelled `Read plate` — not a toggle, because a toggle invites idle flipping.

Read mode changes the entire page chrome so the two are never confused:

- The plate surface shifts from `--plate` to `--ground`, so the working surface visibly recedes.
- A 2px `--control` rule runs the full width beneath the header.
- The header reads `Campaign 24 · read`.
- Control wells gain a 45° hatch **and** `--control` fill. Pattern plus color, never color alone, so the distinction survives colorblindness and greyscale printing.

Read mode is where Type-A and Type-B errors become visible: committed nulls glow at their commit point, and in Type-D campaigns the flip depth draws as a hairline across the branch with every well past it hatched.

---

## 8. Screens

### Bench
Live instrument state, current campaign plate, `FDR_deploy`, the pool and holdout summary. The only screen with a hero numeral.

### Campaign
Full plate at working size, blinded. Batches appear as simultaneous reveals so parallel probing reads as parallel. A branch trajectory strip below the plate shows one selected branch's score path, which is the shape the exploration policy is learning to classify. Inspector on well select.

### Dreaming
Policy revisions as rows, replay score per world as a small-multiple strip. Train and holdout worlds are visually separated by a gutter, not a legend, because the split is structural.

The beta sweep is the one place a conventional line chart is correct: it is a continuous one-dimensional relationship and any other treatment would be affectation.

A revision diff panel shows the policy code change between `π^m` and `π^{m+1}` with the replay-score delta beside it. This is where the operator actually reads what the system decided to change about itself, and it deserves room.

### Book
Deployed signals, forward-test decay curves, sim-versus-live IC divergence.

The equity curve lives here, below the fold, at one third width. It is present because it would be strange to omit, and demoted because promoting it would undo the point of the product.

### Ledger
Trial budget burn, epoch usage, `K_effective` per epoch. Append-only, so it renders as a log rather than a table — no sorting, no editing, reverse chronological.

---

## 9. Data display

**Tabular figures everywhere.** Right-align all numeric columns. Align decimals.

**Significant figures carry meaning.** An IR is 2 decimals, an IC is 3, a p-value is 3 or `<0.001`. Padding a number with digits it has not earned is a lie told in the type.

**Uncertainty renders as extent, not as error bars stapled to a point.** Where a confidence interval exists, show the interval as the primary mark and the point estimate as a hairline within it. Point estimates presented alone are how people convince themselves a noisy result is a finding.

**No sparklines in chrome.** A sparkline without an axis invites pattern-reading in noise, which is the exact cognitive failure this system exists to counteract.

**Small multiples over overlays.** Fifty-two worlds is fifty-two small panels on a shared scale, not fifty-two lines in one frame.

---

## 10. Motion

One orchestrated moment: **the plate read.** When a campaign is unblinded, control wells resolve in over 420ms with a 12ms stagger by index, the chrome shifts, and the hatch draws. It is the only non-user-triggered animation in the product, and it earns its place because a reveal is genuinely what is happening.

Everything else is instant or near-instant. Panel opens 120ms ease-out. Hover states change color with no transition.

No fade-and-slide-up section entrances. No hover lift on wells. `prefers-reduced-motion: reduce` collapses the plate read to a cross-fade.

---

## 11. Quality floor

- Focus rings: 2px `--confirmed` offset 2px, visible on every interactive element, never suppressed.
- Every state distinction carries a non-color channel: pattern, weight, ornament, or position.
- Contrast: `--ink` on `--plate` is roughly 14:1. `--graphite` on `--plate` clears 4.5:1. `--provisional` and `--void` are used on light ground only.
- The plate is keyboard-navigable as a 2D grid, arrow keys between wells, `Enter` to inspect.
- Wells carry `aria-label` describing branch, depth and revealed state — and in blinded mode that label says nothing a sighted operator could not also see. The barrier holds for assistive technology too, which is an easy thing to leak and a total loss when you do.
- Responsive down to 1280px by collapsing the inspector to a drawer. Below that the product is not usable and should say so plainly rather than degrade into a phone layout nobody will work in.

---

## 12. Copy

Lowercase labels in the rail and on chips. Sentence case in prose. No exclamation marks, no personality, no apologies.

Failure states say what happened and what to do:

> Replay determinism broke at 02:14. Dreaming is halted. Scores produced after that time are marked void. Bisect the evaluator image diff to resume.

Empty states are invitations, not decoration:

> No campaigns yet. A campaign needs at least three theme roots — single-theme campaigns teach the policy a family-specific rule that will not transfer.

That second one is the pattern worth copying: the empty state explains a real constraint from the architecture, so the interface teaches the system's logic at the moment the operator is deciding what to do.

---

## 13. Implementation notes

Single-page app, no framework required beyond a router and a rendering library. The plate is the only component with real drawing needs; render it as inline SVG with wells as `<rect>`, not as DOM nodes, because a 500-node campaign at 60fps in the DOM is a fight you do not need to have.

Tokens live in one CSS custom-property block. The confidence treatment is three classes. The provenance chip is a 30-byte function over hash bytes. None of this needs a design-system package.

Fonts self-hosted as woff2 subsets, latin plus the handful of mathematical characters used in labels (`π₀`, `β`, `Δ`, `σ`, `√`).

---

*Companion to the PRD and architecture. Specifies an interface for a research system.*
