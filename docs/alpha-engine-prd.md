# PRD — Agentic Alpha Discovery Engine

**Codename:** NULLIUS — from *nullius in verba*, the Royal Society motto: "take nobody's word for it." Also names the mechanism: planted nulls.
**Version:** 0.2 (draft for build)
**Derived from:** Zheng et al., *Dream-RSI: Recursive Self-Improvement through Evolving Worlds* (Google, 2026)
**Status:** Design complete, unbuilt
**Owner:** _(you)_

**Changed in 0.2 (2026-09-19):** synced to architecture 0.2. §4.5 and M1 now point at the
recorded deferral for learned components (arch §11.2) · M1.5 admits ported ground-truth
worlds (arch §10.6.1) · §12 corrects the GPU prohibition to cover the replay path ·
§14 adds one Fatal risk · §15.1 revises unknown 2.

---

## 0. One-paragraph summary

NULLIUS is a recursively self-improving research system that discovers predictive signals in crypto markets using only free CEX data. It ports Dream-RSI's core mechanism — treating completed discovery history as a replay simulator for cheap off-policy evaluation of *exploration policies* — into a domain where the evaluator is corruptible rather than ground truth. The port is made viable by one addition: hidden null hypotheses planted at the evaluation layer, which restore supervised labels to a domain that otherwise has none. The system's primary product is not a strategy. It is a calibrated, measured, continuously improving **search-and-select policy with a known false discovery rate**.

---

## 1. Problem

### 1.1 What Dream-RSI solves

Long-horizon agentic discovery is bottlenecked by exploration. Fixed strategies cannot improve from accumulated experience; online meta-policy optimization requires long rollouts before feedback arrives. Dream-RSI's insight is that a completed discovery tree already contains every outcome needed to replay alternative search orders at zero execution cost, converting expensive online meta-learning into cheap offline "dreaming."

### 1.2 Why the naive port to trading fails

The paper's guarantee — the selected policy `π_{t+1}` is no worse than `π_t` on the fixed history — holds **only because node scores are trustworthy**. A GPU kernel that runs in 3ms really runs in 3ms. The Lasso objective is checked against a reference.

A backtest Sharpe of 4.0 is a noisy, biased, adversarially exploitable estimate. Port Dream-RSI naively and the cheapness of replay becomes a liability: you have built the most compute-efficient overfitting machine ever assembled, and the meta-policy that "wins" is the one that most efficiently launders in-sample noise into apparent discovery.

### 1.3 The two substitutions that make the port work

| Paper | NULLIUS |
|---|---|
| Scarce resource is **agent calls** | Scarce resource is **statistical degrees of freedom** |
| Node score is **ground truth** | Node score is **corruptible; corruption rate is measured via planted nulls** |

Everything in this document follows from those two lines.

---

## 2. Goals and non-goals

### 2.1 Goals

- **G1.** Discover predictive signals with positive, cost-adjusted, out-of-sample information ratio, using only free public CEX data (REST + websocket).
- **G2.** Maintain a *measured* false discovery rate for the research process itself, not merely a backtest metric for its output.
- **G3.** Close a recursive loop at the exploration layer so that search quality improves with accumulated campaign history.
- **G4.** Produce an honest, automatic count of hypotheses tested, so multiple-testing deflation can be applied correctly rather than guessed.
- **G5.** Fail fast and cheaply. The system must be able to prove its own core thesis wrong at milestone M3 before any capital is at risk.

### 2.2 Non-goals

- **NG1.** Not a strategy optimizer. Entries, exits, sizing, and portfolio construction are fixed, hand-built, version-controlled, and explicitly **outside** the search space.
- **NG2.** Not an execution-latency system. No HFT, no cross-venue latency arbitrage, no colocation.
- **NG3.** Not a capital multiplier on its own. See §11 for the honest arithmetic.
- **NG4.** Does not search the hypothesis *space*. Dream-RSI redistributes compute within a space; it cannot manufacture edge in a space that has none. Choosing the space is a human job (§9).

---

## 3. Core design decision: search signals, not strategies

**A node in the discovery tree is a pure function, not a strategy.**

```python
def signal(ctx: MarketWindow) -> pd.Series:
    """
    ctx exposes ONLY data at or before ctx.t. Enforced by the API,
    not by convention.
    Returns: index=symbol, value=cross-sectional score. Sign and scale
    are free; the evaluator ranks and normalizes.
    """
```

Hard constraints on the searched object:

- Pure. No I/O, no network, no global state, no randomness without a passed seed.
- No access to future data. The `MarketWindow` object physically cannot return data after `ctx.t`.
- No position sizing, no stop-loss, no entry timing, no leverage. Those live downstream.
- Deterministic under a fixed seed, with wall-clock and memory budgets.

### Why this is the highest-leverage decision in the document

| Property | Strategy P&L as score | Signal IC as score |
|---|---|---|
| Sampling theory | Unknown, path-dependent, heavy-tailed | Known; `SE(IC) ≈ 1/√n` |
| Evaluation cost | Path simulation, slow | Vectorized, fast → high replay density |
| Gaming surface | Large (entry/exit/stop tuning) | Small (it forecasts or it doesn't) |
| Decomposability | Aggregate scalar | Per-time, per-regime, per-asset |
| Degrees of freedom | Enormous | Bounded by the signal contract |

Two competent portfolio constructions on the same alpha differ by roughly 15% in realized Sharpe. Two alphas differ by infinity, because one of them is zero. Spend the search where the variance is.

---

## 4. Core mechanism: planted nulls

This is the component that makes Dream-RSI applicable to a corruptible evaluator. It cannot be made incorruptible. Its corruption rate can be measured.

### 4.1 Mechanism

Selected nodes per campaign are designated **nulls**. Critically, the permutation happens at the **evaluation layer, not the data layer**:

1. The agent receives entirely real market data. Nothing is synthetic.
2. It computes its signal on that real data, normally.
3. For a null node, the evaluator scores the signal against **block-permuted forward returns**.
4. Block length ≈ 20 trading days, preserving return autocorrelation and volatility clustering; destroying only the signal-to-target relationship.
5. True out-of-sample edge of a null branch is therefore **exactly zero by construction**.

The agent cannot detect this. There is no synthetic price series to sniff. The features, prices, order books and volumes are all real. Only the scorer knows.

### 4.1.1 Null fraction

```
φ = clip( max(2/W, 0.15), 0.15, 0.35 )        W = parallel workspaces
```

`φ` is a **floor problem, not a rate problem**. A tree needs at least two null roots and two real roots or it contributes almost nothing to either sensitivity or specificity. At `W = 10` a flat 0.15 yields 1.5 expected nulls, which is too thin; at `W = 32` it yields 5 and is fine. So `φ` falls as `W` rises. Concretely: **0.15 is sufficient once `W ≥ 16` and insufficient below it.**

**Null nodes cost compute, not statistical power.** A null node's signal was never compared to real forward returns, so it consumes agent calls and CPU but **not degrees of freedom**. It must not count toward `K` in the deflation term, and must not debit epoch usage in the trial ledger. Since compute is cheap and degrees of freedom are the binding resource (§1.3), the true price of `φ = 0.25` is a quarter of the LLM bill, not a quarter of the research power. Buy more calibration than feels comfortable.

### 4.1.2 Campaign types: root nulls and depth nulls

Root nulls test **selection** — can the policy avoid committing to a noise direction. They are blind to the more common real-world failure: a genuine signal family whose first three refinements are real and whose next twelve are curve-fitting. **Depth nulls** test that.

```
Type-R campaigns (~70%):  φ_root per §4.1.1; null status inherited by the whole subtree
Type-D campaigns (~30%):  all roots real; a branch flips null at depth d, silently
                          and irreversibly; every descendant is null thereafter
```

**Never mix the two within one tree.** Every policy version is scored on every world, so worlds must be homogeneous in what they measure. Mixed trees turn a bad FDR into an unattributable result — selection failure or stopping failure, indistinguishable — and the policy-development agent gets a muddled gradient between revisions.

Two details that matter more than they look:

- **Randomize the flip depth and tie it to branch quality.** `d ~ Geometric(p)` with `p` decreasing in the parent's true IR, so strong mechanisms support more refinement before exhausting. A constant `d` teaches the policy "always stop at depth 4," which is worth nothing. Vary the distribution across campaigns.
- **Separate the error accounting.** Type-A error is committing to a null; Type-B is continuing to deepen past the flip. `β₂` penalizes the first, `β₁` finally earns its keep on the second. In a root-null world, wasted depth is merely inefficient. In a depth-null world, the waste *is* the measurement.

### 4.1.3 Base-rate reweighting (what goes on the dashboard)

In real quant research the fraction of hypotheses with zero true edge is roughly 90–95%. Calibrating on a 25%-null population and deploying into a 92%-null reality produces a systematically under-skeptical policy. The fix is not to raise `φ` to 0.9, which would gut discovery throughput. Sensitivity and specificity are base-rate independent, so measure them where you have power for both, then reweight:

```
FDR_deploy = π₀(1 − specificity) / [ π₀(1 − specificity) + (1 − π₀)·sensitivity ]
             with π₀ ≈ 0.9
```

**`FDR_deploy` is the headline number.** The raw in-campaign rate is an artifact of a design choice and must never be the figure on the dashboard. Joint precision on sensitivity and specificity peaks near `φ = 0.5`; shade down to ~0.25 because campaigns carry a dual mandate and you still need real signals to discover.

### 4.2 Information barrier

`is_null` is visible to **exactly one component**: the replay scorer.

It must never appear in:
- the discovery agent's prompt or context,
- the exploration policy's `observed()` prefix,
- any stored artifact the policy can read during replay,
- any log the policy-development agent reads between revisions.

Violating this silently voids all calibration. Enforce it with a type-level barrier, not a code review.

### 4.3 Detectability guard (mandatory)

Each campaign, run a two-sample Kolmogorov–Smirnov test on the in-sample score distributions of null nodes vs. real nodes. If `p < 0.05`, the nulls are detectable, the agent may be learning to identify them, and the campaign's calibration is **void**. Investigate the block length and permutation scheme before proceeding.

### 4.4 What this buys

Every replay world now carries labels. Directly measurable, for free, per exploration policy:

- **False discovery rate** — fraction of committed picks that are planted nulls.
- **Wasted depth** — how far the policy deepens a null branch before pruning.
- **Overfit-signature detection** — whether it can distinguish null-branch refinement gains from real-branch gains *using prefix information only*.

That last item is the learnable object and the reason the whole system exists.

### 4.5 The overfit signature (what the policy learns to detect)

All prefix-legal, all computable from stored artifacts. **The features split by whether their underlying claim is family-invariant, and this split is load-bearing.**

**Transfers across theme roots** — the robustness family. A real mechanism survives perturbation whether it is momentum or order flow.

- Sensitivity to small perturbations: jitter a lookback ±10%, drop 20% of the universe, shift the window start by 5 days.
- Improvement along a branch correlating with parameter count rather than mechanism change.
- Universe-subsample stability.

**Does not transfer, and inverts sign** — the shape family. Using these globally is worse than not using them.

- **Concentration of contribution** (Gini of per-period P&L). Signals overfitting in cross-sectional momentum, where real edge should be diffuse. In an event-driven family (listings, unlocks, rebalances), concentration is *what a working signal looks like*. Same statistic, opposite meaning.
- **Rolling-IC non-stationarity.** Diagnostic of overfitting in cross-sectional value; simply normal decay in microstructure.
- Gains concentrated in the lowest-liquidity names. A capacity illusion in a large-cap family, the expected footprint in a small-cap one.

**Consequence: partial pooling, not a global classifier.** A single classifier trained across families averages the inverted features into uselessness, or learns the majority family's sign and actively mis-ranks the minority. Model `P(null | features, theme_root)` with family-specific behaviour shrunk toward a global prior. This needs no hierarchical Bayesian machinery: `theme_root` is already in `meta()`, so expose it to the policy and let the policy-development agent write family-conditional thresholds routed through the same `_schedule(beta)` dict. The dreaming loop finds the conditioning if the worlds contain the contrast.

**Read "model `P(null | …)`" as a functional form, not as a mandate to train one.** The default implementation is family-conditional thresholds written by the policy-development agent — code, revised by dreaming, deterministic under replay. Fitting an actual classifier is a separate decision, gated on the M1 triage number and bound by four constraints (CPU-deterministic model class, offline materialization, Z0 provenance, disjoint training worlds). It is recorded in architecture §11.2, and this paragraph is the one most likely to be misread as authorizing it.

**Two enforcement requirements follow.**

1. **Campaigns must be multi-theme.** A single-theme campaign shows the policy a constant, it learns a family-specific rule, and it fails silently on transfer. Enforce theme diversity at `plan_grid` time as a hard constraint, not a preference.
2. **Leave-one-family-out is a standing metric.** Hold an entire theme root out of the dreaming pool, then evaluate on worlds from that theme. It measures transfer directly, costs almost nothing, and is the only honest way to tell learned research discipline from memorized family texture.

---

## 5. Architecture: three nested loops

The paper has two timescales. Trading has three, because one clock cannot be accelerated: new data arrives at one day per day.

### Loop 1 — Inner (minutes): online exploration

Mirrors the paper's stage ①. The exploration policy `π_t` guides the signal agent to expand a discovery tree over a training epoch.

- `CONTINUE(v)` = resume node `v`'s workspace, generate and evaluate one refined signal.
- Root = a fresh research theme (§9).
- `W` parallel workers = concurrent evaluation slots.
- Every attempt is logged to the tree with its full artifact.

### Loop 2 — Middle (hours): dreaming

Mirrors stages ② and ③. The completed tree joins the replay pool. The policy-development agent produces `M` revisions of `π`'s code, each replayed across all stored worlds, and `π_{t+1} = argmax_m V^m`.

The paper's selection guarantee carries over unchanged: because the candidate set includes `π^0 = π_t`, the selected policy is no worse than the current one *on the fixed replay history*. Note the qualifier. It is a guarantee about replay score, not about future P&L.

### Loop 3 — Outer (months): forward-test recalibration

New to NULLIUS, and the only source of genuinely uncontaminated evidence.

- Every promoted signal is timestamped and its live forward IC tracked from the promotion date forward.
- After 90 days, that signal has a track record on data that **did not exist when the hypothesis was formed**. No purging scheme is needed; the data is honestly out of sample by construction.
- Those outcomes become labels. They recalibrate `β₄` (sim-reality divergence), the decay priors, and which signal families the objective should reward.

This loop is slow, low-bandwidth, and the most valuable signal in the system.

---

## 6. Data model

### 6.1 Node schema

```yaml
node:
  id: uuid
  parent_id: uuid | null
  theme_root: enum          # see §9
  depth: int
  campaign_id: uuid

  construction:
    code: str               # the pure signal function
    code_hash: sha256
    stated_mechanism: str   # agent's economic rationale; used for dedup
                            # and human review ONLY. Never scored.

  artifact:                 # full time series, not just scalars
    signal_returns: series  # per-asset, per-period, post-cost
    ic_series: series
    turnover_series: series
    decay_profile: array    # IC at h = 1, 2, 5, 10, 20 periods
    capacity_estimate: float
    regime_attribution: dict

  metrics:
    ic_mean: float
    ic_tstat: float
    ir_standalone: float
    ir_marginal: float      # vs. current book — see §6.2
    turnover: float
    cost_adjusted_ir: float
    perturbation_stability: float

  provenance:
    evaluator_hash: sha256
    data_snapshot_hash: sha256
    cost_model_hash: sha256
    agent_model_id: str       # provider/model/version — pinned, not a rolling alias
    agent_ckpt_hash: sha256   # non-null for self-hosted weights
    agent_sampling: dict      # temperature, top_p, thinking, seed
    trials_charged: int
    trial_ledger_id: uuid

  hidden:                   # scorer-only. See §4.2.
    is_null: bool
    permutation_seed: int
```

### 6.2 Node value is contextual

Unlike the paper, where `s_v` is absolute, a signal's value **depends on what you already hold**. A new signal correlated 0.9 with the existing book is nearly worthless regardless of standalone IR.

This is why the artifact stores the **full signal return series**, not just a scalar. Marginal contribution against any book is then computable at replay time from stored data, so the same node can be scored differently depending on the path the policy took to reach it. Replay stays deterministic. The evaluation stays rich.

```
ir_marginal(v | book) = IR(book ∪ {v}) − IR(book)
```

### 6.3 Evaluator immutability (hard invariant)

Every score is stored under the triple `(evaluator_hash, data_snapshot_hash, cost_model_hash)`.

**The self-improvement loop must not be able to modify the evaluator.** The paper states this as a design choice; here it is a safety property. A system that can edit its own validator will "improve" by weakening it. Enforce with a read-only mount and a CI check on the hash.

Consequence: changing the fee model or extending the data invalidates every cached score. The tree *structure* survives; the scores do not and must be recomputed. Budget for this.

---

## 7. The replay objective

### 7.1 Per-world score

The paper's Equation 1 is `max_v s_v − β₁N + β₂·parallelism`. Taking `max` over revealed in-sample scores is precisely the selection-bias generator. Two changes.

**Change A — the policy must commit, and is scored out of sample.** During replay the policy sees only in-sample metrics and diagnostics. On termination it must emit `v̂`, the signal it would deploy. It is scored on a **sequestered epoch it has never observed in any world**. This shifts the meta-learning target from "how to search efficiently" to "how to search *and select* without fooling yourself."

**Change B — parallelism bonus becomes a statistical-budget penalty.** Backtests are embarrassingly parallel and cheap. Parallelism is not the bottleneck. Data is.

```
V_i^m =   IR_oos( π^m.commit() | book_t )     # committed pick, sequestered epoch
        − β₁ · trials_charged                 # statistical budget consumed
        − β₂ · null_pick_rate                 # planted-null false discoveries
        − β₃ · deflation(K_eff)               # multiple-testing haircut, §7.3
        − β₄ · | IC_forward − IC_backtest |   # sim-reality divergence
        − β₅ · switch_cost · n_regime_switches
        + β₆ · orthogonality(committed book)
```

`β₂` is the term that does not exist in the paper and without which none of this works.

`β₄` is computable only for nodes that have been through the forward-test queue. It teaches the meta-policy to prefer signal families whose backtests are **honest**, not merely high.

### 7.2 Cross-world aggregation: CVaR, not mean

The paper averages: `V^m = (1/t) Σ V_i^m`. That is correct only if worlds are exchangeable. **Market regimes are not exchangeable.** A policy that is brilliant in trending worlds and catastrophic in chop averages to "fine" and then blows up.

```
V^m = (1 − λ) · mean_g( V_g^m )  +  λ · min_g( V_g^m )      λ ∈ [0.5, 0.7]
```

where `g` indexes regime strata. Two lines of code, larger impact than anything else in this section.

### 7.3 Multiple-testing deflation, and why search still pays

Expected maximum Sharpe under the null across `K` trials grows like `√(2 ln K)`, in units of `SE(Sharpe)`:

| K (trials) | Null max-Sharpe bar |
|---|---|
| 10 | 2.15 |
| 100 | 3.03 |
| 1,000 | 3.72 |
| 10,000 | 4.29 |
| 100,000 | 4.80 |

With `T` years of daily data, `SE(annualized Sharpe) ≈ √(1/T)`:

| Data | K = 1,000 | K = 100,000 |
|---|---|---|
| 3 years | 2.15 | 2.77 |
| 5 years | 1.66 | 2.15 |
| 8 years | 1.32 | 1.70 |

**This is the justification for the entire machine.** Going from 1,000 to 100,000 hypotheses raises your significance bar by about 30% while giving you 100× more shots. The logarithm is on your side. Search wins.

It only wins if `K` is counted honestly. The universal failure in discretionary quant research is counting "strategies I wrote down" rather than "hypotheses I implicitly tested," which understates `K` by one to two orders of magnitude. **The discovery tree is an automatic, honest trial counter.** That property alone justifies the architecture.

### 7.4 The beta knob

Keep the paper's single-scalar discipline verbatim: one `beta` controlling explore/exploit, patience, and pruning aggressiveness; **fixed within an episode**; swept on a grid during offline evaluation; default chosen per cycle from live evidence and prior sweeps. It is good design and it is what makes cross-cycle comparison legible.

Add one role: `beta` also gates **overfit aversion**. High beta tolerates longer branches before demanding OOS confirmation; low beta prunes on the first sign of the §4.5 signature.

---

## 8. Component specification

### C1 — Data spine

| Field | Spec |
|---|---|
| Sources | Binance/OKX/Bybit REST + websocket. Klines (1m/1h/1d), aggTrades, L2 book diffs @100ms, funding, **margin borrow rates**, `exchangeInfo` filters |
| Storage | Parquet, partitioned `symbol/date`, immutable, content-hashed snapshots |
| Universe | Top-N by 30d median dollar volume, **survivorship-bias-free** — delisted symbols must remain in history or every cross-sectional result is a lie |
| Regime labeler | Rolling-window fit only. Fitting an HMM on full history and then finding that signal X works in regime 2 is leakage, because regime 2 was labeled with future data. |

Regime features (all free): multi-horizon realized vol and vol-of-vol; cross-sectional return dispersion; return autocorrelation at several lags; mean pairwise correlation of the top 50; breadth above an N-day MA; depth-at-10bps trend from L2; margin borrow rate level.

### C2 — Frozen evaluator

Responsibilities, in order:

1. Execute the signal function against the sequestered epoch under a wall-clock budget.
2. Apply purged k-fold with embargo — purge `H` (holding period), embargo `L` (lookback) around every split.
3. Apply the cost model (§10).
4. Compute marginal IR against the current book.
5. **Inject the null permutation** for designated nodes.
6. Run leakage tripwires (§C6).
7. Debit the trial ledger.
8. Emit the full artifact.

Immutable. Hash-pinned. The loop cannot modify it.

### C3 — Discovery agent

A coding agent writing signal functions against the §3 contract. Adapt the paper's Listing 1 exploration prompt nearly verbatim, keeping in particular:

- The requirement to read the complete history before proposing.
- The distinction between a flawed core mechanism and a good idea let down by a bug — the former is not worth retrying, the latter is, but only with the bug actually located in code rather than guessed from the write-up.
- The explicit anti-convergence clause. Without it, a discovery tree collapses into 400 parameter tweaks of one indicator.

**Model tiering.** Roots and depth are different jobs and should not use the same model. Named models per role, with verified rates, are in architecture §14.2. A bad proposal at depth is caught by the evaluator for one trial charge; a converged tree at roots is caught by nothing, because every node scores plausibly. Roots get a frontier model rotated across providers; depth gets a cheap model with a 1M context, because the read-everything requirement below makes context a hard selection criterion. Full specification, costs and provenance requirements in architecture §14.1.

**Do not inject high-level directional guidance from history into the prompt.** The paper's Figure 5 found this consistently *underperformed* the unguided version across both paradigms, because strong semantic priors about future search directions over-constrain the space and impede diverse exploration. Keep history as an interactive replay object, not as prose advice. This is counterintuitive and most implementations get it backwards.

### C4 — Exploration policy (the searched meta-object)

Mirror the paper's prefix-only API:

```python
question.observed()        -> dict[node_id, Observation]   # revealed prefix only
question.legal_actions()   -> list[node_id]                # roots + open frontiers
question.legal_roots()     -> list[node_id]
question.probe_batch(cells, on_reveal=...)
question.budget_remaining()                                # statistical, not compute
question.commit(node_id)                                   # REQUIRED at termination
```

Plus `plan_grid(context) -> GridPlan(branch_count=W, refine_count=R)`, run **before** a campaign, using only prior-campaign manifests. Never inspects the current episode.

**Frontier-difficulty depth allocation.** `plan_grid` as originally specified chooses width versus depth from prior manifests but has no notion of difficulty targeting, so it cannot tell an exhausted theme from an unexplored one. Borrow the mechanism from self-improving-model training: target a per-branch success rate near `p* ≈ 0.2`.

```
D(branch) = exp( −(p_branch − p*)² / 2σ² )      p* = 0.2
```

A branch where nearly every refinement succeeds is saturated and loses allocation; one where nothing succeeds is beyond the agent's frontier and also loses it. Depth flows to branches sitting at the edge of what the discovery agent can actually do, which is where the informative trials are. Computable entirely from prefix information, and it drops into the same `_schedule(beta)` dict as every other threshold.

Hard constraints carried over from the paper: prefix-only decisions; no unrevealed scores; no hardcoded node ids; no absolute score targets; must terminate when no batch is selected.

One addition: `commit()` is mandatory. A policy that terminates without committing scores `−∞`.

### C5 — Dreaming engine

Per outer iteration: hold the replay pool fixed, run `M` code revisions of `π`, evaluate each on every stored tree, select the argmax under §7. Feed replay trajectories back to the policy-development agent between revisions.

### C6 — Leakage tripwires

Run periodically on any candidate; a failure poisons the node **and its entire subtree**, which is excised from the replay pool:

- Score against time-shuffled forward returns. Surviving Sharpe means leakage.
- Score against label-permuted targets. Same test, different permutation.
- Re-run with a different seed, a different start offset, a different universe subsample. Degradation beyond threshold is a reject.

### C7 — Regime coverage ledger

The paper's replay pool grows monotonically and that is fine when outcomes are ground truth. Yours is indexed by calendar time. Run six months in low-vol chop and your entire pool is low-vol chop; the meta-policy learns a chop-optimal search policy and you find out when the regime breaks.

- Maintain an explicit ledger: `{high-vol trend: 2, low-vol chop: 14, crash: 0, …}`.
- **Block promotion** when the regime being deployed into has coverage below threshold.
- Backfill by replaying stored discovery trees against historical market epochs they were never actually run on.

### C8 — Portfolio construction (fixed, NOT searched)

Signal book → IR-weighted combination with shrinkage → volatility targeting → position and concentration limits → orders. Version-controlled, human-authored, explicitly outside the search space. Changing it is a human decision with a changelog entry, not a discovery.

### C9 — Execution

- Read `LOT_SIZE`, `NOTIONAL`, `PRICE_FILTER`, `stepSize`, `tickSize` from `exchangeInfo` at startup and daily. Never hardcode.
- Post-only by default; taker only when signal decay horizon < expected fill time.
- Isolated margin per book. Cross margin turns independent positions into one position with N legs.
- Rate-limit-aware order router with exponential backoff.

### C10 — Risk and kill switches

- Hard equity floor at `2 × min_notional`. Below it, stop rather than degrade into untradeable dust.
- Daily loss limit → flatten and halt.
- Sim-reality divergence monitor: if live IC falls below 40% of backtest IC over a statistically meaningful window, demote automatically.
- Staleness watchdog on the data feed.

---

## 9. Hypothesis space (the human's job)

Dream-RSI improves *search efficiency within a space*. It cannot create edge in a space that has none. Choosing the space is the highest-value human input in the system, and it should be encoded as the set of legal `theme_root` values.

### 9.1 Structural advantages available to a small operator

| Advantage | How to exploit it |
|---|---|
| **Capacity** | Anything that works on $50k but not $50M is invisible to professionals and therefore uncrowded. Small-cap cross-section is the canonical case. Most retail waste this by trading BTC. |
| **Undercomputed free data** | L2 and tape are public; the *features* are not. OFI, queue dynamics, trade-size distribution, cancel/replace rates, iceberg detection. Information advantage manufactured by compute. |
| **Borrow rates as short-interest proxy** | Margin borrow rate and utilization from the free margin API is a real-time crowding indicator that substitutes for paid short-interest data. |
| **Mechanical calendar effects** | Listings, index rebalances, token unlock schedules, funding settlement times. Public, dated, mechanically predictable. |
| **Patience** | No benchmark, no redemptions, can hold 100% cash for months. Regime-conditional strategies a fund could never run. |

### 9.2 Breadth is the cheapest multiplier

Fundamental law of active management: `IR ≈ IC × √breadth`.

An IC of 0.03 is unimpressive in isolation. Across 100 names × 250 days with an effective breadth of ~1,250 independent bets, it yields `IR ≈ 0.03 × √1250 ≈ 1.06`.

**Point the search at the cross-section.** Breadth is free there and nowhere else.

### 9.3 Theme roots (initial set)

1. Cross-sectional momentum and short-term reversal, small/mid-cap universe
2. Order-flow imbalance and microstructure features from the free L2 feed
3. Borrow-rate and funding-state conditioning
4. Volatility-state and dispersion regimes
5. Mechanical calendar and event effects
6. Cross-asset and cross-venue state divergence (state, not price)

### 9.4 What is structurally dead at retail scale

Triangular arbitrage, cross-exchange latency arbitrage, anything with a holding period under ~30 minutes taking liquidity. Do not let the agent open roots there.

---

## 10. Cost model

Fee drag is the constraint that determines viable signal frequency, so it belongs in the evaluator, not in a footnote.

- Binance VIP0 spot: 0.1% maker/taker; 0.075% with BNB deduction. Round trip ≈ 0.2%.
- One round trip per day compounds to `0.998^365 ≈ 0.48`. **Half your equity to fees in a year before any strategy P&L.**
- Zero-maker venues exist (MEXC 0% maker / 0.05% taker; Binance.US 0% maker / 0.02% taker, all pairs, no volume tier). Verify current schedules before relying on them.
- Going 0%-maker does not make trading free. It converts fee cost into **adverse-selection cost on passive fills**, which the evaluator must model explicitly (queue-position penalty, fill only when the tape trades through your price) or the simulator will lie.

The evaluator's `cost_adjusted_ir` must reflect the actual venue and order type. A signal with 0.05% average edge per trade is worthless at 0.2% round trip and interesting at 0% maker. `β₆` in §7.1 makes the meta-policy feel this directly.

---

## 11. Success metrics

Deliberately, **none of the primary metrics is a backtest Sharpe.**

| Tier | Metric | Target |
|---|---|---|
| **Primary** | `FDR_deploy` — base-rate-reweighted false discovery rate (§4.1.3) | < 25% at π₀ = 0.9 |
| **Primary** | Paired ΔIR of committed picks, dreaming vs. fixed baseline | > 0.3 IR, `p < 0.05` |
| **Primary** | Leave-one-family-out transfer: ΔIR on a held-out theme root | > 0 |
| **Secondary** | Sensitivity / specificity on planted nulls (base-rate independent) | tracked, not targeted |
| **Secondary** | Type-B error rate: depth past the flip in Type-D worlds | falling across campaigns |
| **Secondary** | Forward-test IC retention: live IC ÷ backtest IC at 90 days | > 0.5 |
| **Secondary** | Discoveries per 1,000 trials charged (nulls excluded from the denominator) | trending up |
| **Secondary** | Regime coverage breadth of the replay pool | ≥ 3 strata, none empty |
| **Tertiary** | Cost-adjusted IR of the deployed book | > 0.8 |
| **Tertiary** | Sim-reality divergence `\|IC_live − IC_sim\|` | shrinking across campaigns |

### 11.0 Why the primary statistic is continuous, not binary

Raw FDR is a proportion, and proportions are power-poor. Detecting `0.30 → 0.21` at 80% power needs ~364 independent commits per arm; replays clustered by world inflate that by the design effect to well over a thousand. That test is not buildable at this scale.

Fix the statistic, not the ambition. **Score each commit continuously** using the out-of-sample IR of the committed pick, which is continuous and zero in expectation under the null, and run the comparison **paired** — same policy pair, same worlds. A paired t-test detecting `ΔIR = 0.3` with `σ_diff ≈ 0.8` needs ~56 worlds, which is reachable. `FDR_deploy` stays as the interpretable summary on the dashboard; the gate runs on the paired continuous difference.

### 11.1 The honest capital arithmetic

A system built exactly as specified, run competently and with luck, plausibly produces a strategy with live Sharpe in the 0.8–1.5 range and 30–80% annualized at low leverage. That compounds $10 into roughly $15 in a year. It compounds $50,000 into $70,000–$90,000 in a year using the identical code.

Small capital is a **fidelity harness**, not a capital base: its job is to prove that live fills, latency, partial fills, rounding, rate limits and borrow costs match the simulator to within a few basis points. That measurement is the deliverable. Capital scales; edge is what is scarce.

Most systematic retail crypto attempts lose money. This document does not change that base rate; it only makes the failure measurable and fast.

---

## 12. Build order

Each milestone has an explicit exit criterion. Do not advance without meeting it.

**Budget to the M3 gate: roughly $1,100–1,500 in LLM spend** under the tiering and named model registry in architecture §14.1–14.2, or $7,200–9,600 if every role runs on a frontier model. No GPU is required anywhere in the research or live path, and GPU is in fact *prohibited* in both the eval and replay paths by the architecture §12 determinism contract — replay calls no model of any kind (architecture §11.2). That figure is what "learn it for the cost of compute, with zero capital at risk" costs in practice.

### M0 — Data spine, signal contract, frozen evaluator
No agent. Hand-write 5 signals. **Exit:** evaluator reproduces known results (cross-sectional momentum shows positive IC in crypto; a random signal shows IC indistinguishable from zero). Survivorship bias verified absent.

### M1 — Leakage tripwires and planted nulls
**Exit:** a deliberately leaking signal is caught by every tripwire, *and* the §4.3 KS test confirms null nodes are statistically indistinguishable from real nodes in sample.

**Run the one-day triage experiment here, before building anything downstream.** Measure how well *perturbation stability alone* separates planted nulls from real signals.

- **AUC ≈ 0.85** — a single robustness statistic does the job. Hard-code the filter, delete the dreaming apparatus, save months. The project's interesting claim is false in the cheap direction.
- **AUC ≈ 0.6** — the learned signature is exactly where the value lives, and M3 is worth building toward. This is also the only branch on which fitting a §4.5 classifier is admissible at all, and it arrives with conditions attached (architecture §11.2).

That one number tells you whether the thesis is interesting. It costs a day and should gate the entire M2–M3 investment.

### M1.5 — Bootstrap worlds (non-financial)
A replay world does not have to be a crypto campaign. The paper runs the same framework across Lasso solving, circle packing and KernelBench. Run campaigns on **non-financial discovery tasks with ground-truth evaluators** — hyperparameter search, feature selection on labeled ML benchmarks, symbolic regression against known targets. These train the *same* exploration policy on the *same* problem structure with perfect labels, zero statistical-budget cost, and no waiting for market time.

**Porting one beats writing one.** An existing open-licensed environment with an exact oracle arrives with published baselines to validate the harness against, which a domain written here does not have. Take the environment and the oracle; take nothing else from it. Provenance and the refusal rule for a changed upstream are in architecture §10.6.1.

**Exit:** 40–50 bootstrap worlds in the pool, each carrying its source commit and dataset manifest hash. This converts the M3 pool-size constraint from a calendar problem into a compute problem, and compute is purchasable.

### M2 — Discovery agent + tree, fixed exploration policy
The paper's "Recursive Fixed Exploration" baseline. **Exit:** a measured baseline on planted nulls — sensitivity, specificity, and per-commit OOS IR. These are the control for everything after.

### M3 — Replay pool + dreaming ⟵ **THE GATE**

**Precondition:** ≥ 50 worlds in the pool (§12.1). Below 20, do not run dreaming at all.

**Exit, all three:**
1. Paired ΔIR of committed picks > 0.3 with `p < 0.05`, dreaming vs. the M2 fixed baseline, on worlds held out of the dreaming loop.
2. `FDR_deploy` improves at π₀ = 0.9.
3. Leave-one-family-out transfer ΔIR > 0.

**If M3 fails, stop.** The core thesis — that a search-and-select policy can be meta-learned to resist overfitting — is false in this domain, and you have learned it for the cost of compute, with zero capital at risk. This is the single most valuable property of the whole design. Do not skip it, do not soften the criterion, and do not proceed to M4 on a marginal result.

### 12.1 Minimum viable pool size, and meta-level overfitting

The dreaming loop **overfits its own replay pool**. The paper's guarantee `V^{m★} ≥ V^0` holds on the *fixed history*; selecting the max over `M` revisions scored on a handful of worlds is the same multiple-testing problem one level up, and the paper does not confront it because its scores are ground truth.

Applying the `√(2 ln M)` bar at the meta level, with `SE(V) ≈ σ_V/√n_worlds`, the selected policy's true advantage survives selection noise only when:

```
true_advantage  >  √(2 ln M) · σ_V / √n_worlds
```

At `M = 40` (bar ≈ 2.72), `σ_V ≈ 0.8` and a target advantage of 0.3, this gives **n > 53 worlds** — independently reproducing the ~56 from the paired-power calculation in §11.0.

| Pool size | Operating regime |
|---|---|
| < 20 worlds | **Do not run dreaming.** Fixed exploration; accumulate history |
| 20–50 | Dreaming with `M` capped at 8–10 so the selection bar stays low. Cap policy complexity |
| 50+ | Full dreaming, `M = 30–40`, 70/30 train/holdout split on worlds, holdout rotated each cycle |

Tree resampling (subsampling roots from existing campaigns) inflates `n` cheaply, but be honest that it inflates `n_effective` by far less than `n`.

### M4 — Portfolio construction + live shadow
Paper trading against the live feed with real order placement on a sub-account. Pre-register success criteria in a hashed file **before** the shadow run starts. **Exit:** 90 days of shadow with pre-registered criteria met and a statistically meaningful trade count.

### M5 — Live capital, outer loop closes
Minimum size. Forward-test queue begins feeding `β₄`. **Exit:** none. This is steady state.

---

## 13. Invariants

Violating any of these silently invalidates the system. Enforce in CI, not in code review.

1. The self-improvement loop **cannot modify the evaluator, cost model, or data snapshot**.
2. `is_null` is readable by exactly one component: the replay scorer.
3. The exploration policy sees **prefix-only** information. No unrevealed scores, no absolute score targets, no hardcoded node ids.
4. Sequestered epochs are retired permanently after **3 promotion decisions**. Track in a ledger. When clean epochs run out, the system stops. That is a legitimate terminal state.
5. Every score carries `(evaluator_hash, data_snapshot_hash, cost_model_hash)`. Mismatched scores are never compared.
5a. Every node records `agent_model_id`. Provider aliases re-route silently; a pinned snapshot or a self-hosted checkpoint hash is the only real guarantee. M3 results are reported per model stratum as well as pooled.
6. Regime labeling is causal. Rolling-window fit only.
7. Promotion criteria are pre-registered and hashed before the evaluation that decides them.
8. The trial ledger is append-only.

---

## 14. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Agent learns to detect planted nulls | Fatal (voids all calibration) | §4.3 KS guard every campaign; vary block length; rotate permutation scheme |
| **A fitted §4.5 classifier is scored on campaigns whose nulls it trained on** | Fatal (voids all calibration, and flatters) | Only reachable on the AUC ≈ 0.6 branch. Training worlds and dreaming worlds held disjoint and rotated independently; arch §11.2 |
| Replay pool is regime-monotone | High | §C7 coverage ledger with promotion block |
| Evaluator drift invalidates the pool | High | Content-addressed provenance; budgeted re-scoring |
| Sequestered data exhaustion | Medium, inevitable | Epoch ledger; accept the terminal state rather than reuse |
| Alpha decay outpaces discovery | Medium | Forward-test loop measures decay empirically; feed half-life into `plan_grid` |
| Hypothesis space is barren | High | Not solvable by the architecture. §9 is a human responsibility; revisit quarterly |
| Cost model optimism | High | Live shadow reconciliation; `β₄` penalty |
| **Dreaming overfits its own replay pool** | High | §12.1 pool-size regimes; cap `M` when thin; 70/30 world holdout, rotated |
| **Overfit signature is family-specific** | Medium | §4.5 partial pooling; enforced multi-theme campaigns; leave-one-family-out metric |
| Binary FDR gate is under-powered | Medium | §11.0 paired continuous statistic; FDR kept as summary only |
| **Agent model silently re-routed mid-pool** | High | `agent_model_id` per node; self-host pinned weights for M3-feeding campaigns; stratify (arch §14.1) |
| Signal agent too weak, read as a failed thesis | High | Measure `mechanism_discrimination` at M2, before the gate (arch §14.1) |

---

## 15. Resolved design decisions

All five original open questions are closed. Each resolution is load-bearing; the reasoning lives in the section cited.

| # | Question | Resolution | Section |
|---|---|---|---|
| 1 | Right value of `φ`? | `clip(max(2/W, 0.15), 0.15, 0.35)`. It is a floor problem, not a rate problem. Nulls cost compute, not degrees of freedom, so buy more calibration than feels comfortable. Report `FDR_deploy` reweighted to π₀ ≈ 0.9, never the raw in-campaign rate. | §4.1.1, §4.1.3 |
| 2 | Root nulls only, or mid-branch? | **Both**, in separate campaign types (70% Type-R, 30% Type-D), never mixed within one tree. Randomized flip depth tied to branch quality. Type-A and Type-B errors accounted separately. | §4.1.2 |
| 3 | Is `ir_marginal` cheap enough? | **Yes — and the premise was wrong.** Arithmetic is microseconds (rank-1 update against a book that is fixed during a replay). The real cost is artifact I/O. Cache the return series as one dense in-RAM array per campaign, not the marginal IR. | §6.2 |
| 4 | Minimum replay pool size? | **~50–60 worlds**, derived twice independently (meta-level selection bar and paired-test power). Below 20, dreaming yields a policy confidently worse than fixed exploration. Bootstrap the cold start with non-financial ground-truth worlds. | §12.1, M1.5 |
| 5 | Does the overfit signature transfer? | **Partially.** Robustness features transfer; shape features do not and two of them invert sign across families. Use partial pooling with family-conditional thresholds, enforce multi-theme campaigns, track leave-one-family-out. | §4.5 |

### 15.1 Remaining unknowns

Genuinely open, to be answered empirically rather than by design:

1. Does the perturbation-stability AUC land near 0.6 or near 0.85? This decides whether the dreaming apparatus is necessary at all, and the M1 triage experiment answers it in a day.
2. Does policy skill learned on non-financial bootstrap worlds actually transfer to financial ones, or does it merely pad `n` without adding `n_effective`? Measurable by comparing dreaming gains on financial worlds with and without the bootstrap pool. Porting worlds rather than authoring them (M1.5) makes this answerable earlier and more cheaply, which matters because a negative answer invalidates the M1.5 shortcut rather than the thesis.
3. What is the true `σ_V` across worlds? Every power calculation here assumes ≈ 0.8. Re-derive from the first 20 worlds and revise §12.1 accordingly.
4. What is `π₀` for *this* hypothesis space specifically? The 0.9 figure is a literature prior; the forward-test queue measures the real one after roughly a year.

---

## Appendix A — Mapping to the paper

| Dream-RSI | NULLIUS |
|---|---|
| Discovery agent | Signal-authoring agent (§C3) |
| Evaluator (fixed) | Frozen evaluator + cost model + validator (§C2) |
| Node `v` | Signal hypothesis with full artifact (§6.1) |
| Score `s_v` | `ir_marginal` against the current book (§6.2) |
| `CONTINUE(v)` | Refine and re-evaluate one signal |
| Root | Research theme (§9.3) |
| Discovery tree `T_t` | One campaign |
| Replay world | Re-navigating a campaign with a different policy |
| Exploration policy `π` | Search-and-select policy (§C4) |
| `V_i^m` (Eq. 1) | §7.1, with committed selection + null penalty |
| Mean over worlds | CVaR over regime strata (§7.2) |
| `β₁ N` (agent calls) | `β₁ ·` trials charged (statistical budget) |
| Parallelism bonus | Removed; replaced by budget and overfit penalties |
| `plan_grid` | Same, driven by campaign manifests |
| Figure 5 (guidance hurts) | §C3: do not inject prose history into prompts |
| Figure 6 (adaptive effort) | Research intensity keyed to live edge decay |

## Appendix B — Reference formulas

```
Null max-Sharpe bar across K trials    ≈ √(2 ln K)          [in SE units]
SE(annualized Sharpe), T years          ≈ √(1/T)
Fundamental law                          IR ≈ IC × √breadth
SE(IC), n observations                  ≈ 1/√n
Fee drag, r round trips/yr at c         = (1 − 2c)^r
Kelly fraction, Sharpe S, vol σ          f* = S/σ   (use ≤ ¼ Kelly)
Effective independent bets, corr ρ       N_eff = N / (1 + (N−1)ρ)

Meta-level selection bar, M revisions    advantage > √(2 ln M) · σ_V / √n_worlds
Base-rate reweighted FDR                 FDR_deploy = π₀(1−spec) / [π₀(1−spec) + (1−π₀)·sens]
Null fraction                            φ = clip(max(2/W, 0.15), 0.15, 0.35)
Paired-test n for ΔIR at 80% power       n ≈ 8(σ_diff/Δ)²   → ~56 at σ=0.8, Δ=0.3
```

---

*This document specifies a research system, not investment advice. Systematic trading carries substantial risk of total loss, and the expected outcome of a small live account is losing it.*
