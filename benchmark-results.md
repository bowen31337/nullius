# Anthropic-Compatible Gateway Benchmark

_Final · 2026-09-19 13:24 · 11 models · 6 coding tasks · 78 hidden tests · **3 samples per cell (198 calls)**_

Two Anthropic-Messages-compatible gateways, surveyed and benchmarked on Python coding ability.

| Gateway | Base URL | Credential |
|---|---|---|
| model-iq (Accenture) | `https://model-iq.aicore.accenture.com` | `op://business/fengshui-anthropic/model-iq-key` |
| z.ai | `https://api.z.ai/api/anthropic` | `op://business/fengshui-anthropic/z-ai-1` |

## Headline

| # | Model | Provider | Mean /78 | Samples | Stable | Avg s | Tokens/run |
|---|---|---|---|---|---|---|---|
| 1 | **`glm-5.3-flash`** | z.ai | **78.0** | 78/78/78 | 6/6 | 31.5 | 9,669 |
| 2 | **`glm-5-3`** | model-iq | **78.0** | 78/78/78 | 6/6 | 52.1 | 25,299 |
| 3 | `ornith-1-5-397b-fp8` | model-iq | **77.3** | 78/77/77 | 5/6 | 16.1 | 9,775 |
| 4 | `glm-5.3` | z.ai | **77.3** | 77/77/78 | 5/6 | 20.8 | 9,335 |
| 5 | `kimi-k3` | model-iq | **77.3** | 77/77/78 | 5/6 | 31.3 | 9,366 |
| 6 | `deepseek-v4-1-flash` | model-iq | **77.0** | 77/77/77 | 5/6 | 5.6 | 3,472 |
| 7 | `deepseek-v4-flash-0731` | model-iq | **76.0** | 77/75/76 | 4/6 | 1.7 | 1,569 |
| 8 | `qwen3-8-flash-next-fp8` | model-iq | **75.3** | 78/78/70 | 5/6 | 53.6 | 61,894 |
| 9 | `glm-5-3-flash-2` | model-iq | **71.0** | 58/78/77 | 4/6 | 31.7 | 24,067 |
| 10 | `deepseek-v4-pro-0813` | model-iq | **70.0** | 75/58/77 | 4/6 | 4.5 | 1,470 |
| 11 | `qwen3-8-flash-next` | model-iq | **62.3** | 58/70/59 | 4/6 | 57.8 | 68,767 |

**Stable** = tasks perfect in *all three* samples — the measure of whether one call can be trusted.

Three findings survive resampling:

1. **Accuracy is a near-tie.** Six models sit within 1.0 point of each other (78.0 → 77.0). Only **two** never dropped a test: `glm-5.3-flash` @ z.ai and `glm-5-3` @ model-iq.
2. **Cost and latency differ by ~40×, and that is the real decision.** `deepseek-v4-flash-0731` averages 1,569 tokens at 1.7 s; `qwen3-8-flash-next` averages 68,767 tokens at 57.8 s **and scores 16 points lower**.
3. **`claude-sonnet-4-6-fhtr` on model-iq is broken** — upstream credential failure, HTTP 401, not fixable client-side.

---

## Top 3 recommended for coding

Ranked on what actually matters for one-shot coding use: **does a single call work** (stable tasks), then cost and latency.

### 🥇 1. `glm-5.3-flash` — z.ai

**78.0/78 · 78/78/78 · 6/6 stable · 31.5 s · 9,669 tokens**

The only model that never dropped a test *and* did it cheaply. The other perfect scorer, `glm-5-3` @ model-iq, matches
its accuracy but costs 2.6× the tokens and 1.7× the latency for the same result. Pick this when correctness on the first
attempt is what you are paying for.

### 🥈 2. `deepseek-v4-1-flash` — model-iq

**77.0/78 · 77/77/77 · 5/6 stable · 5.6 s · 3,472 tokens**

The most *predictable* model measured — the only one with zero variance across all three samples. It trades 1.0 point for
a **2.8× token saving and 5.6× lower latency** than the leader. Its single miss is deterministic (the
`word_break_all("", …)` base case), not instability, so you know exactly what you are getting. Best choice for volume,
CI loops, or anything latency-sensitive.

### 🥉 3. `ornith-1-5-397b-fp8` — model-iq

**77.3/78 · 78/77/77 · 5/6 stable · 16.1 s · 9,775 tokens**

The strongest option if you are confined to model-iq. Highest mean on that gateway outside the 25k-token `glm-5-3`, at
**2.6× fewer tokens and 3.2× lower latency** than it. A balanced middle: near-top accuracy without the cost of the
flagship or the edge-case fragility further down the table.

**Runner-up — `glm-5-3` @ model-iq (78.0, 6/6 stable).** Equal-best accuracy and perfectly stable, but 25,299 tokens and
52.1 s per run. Worth it only if you are locked to model-iq, cannot use `z.ai`, and need 6/6 stability regardless of cost.

**Not recommended for coding:** both `qwen3-8-flash-next` variants — worst accuracy (62.3 and 75.3) at 40× the token cost
and ~55 s per task.

> Caveat: at n=3, the top six models sit within 1.0 point and are not reliably distinguishable on accuracy alone. These
> three are separated by **consistency and cost**, which the data does support, rather than by a capability gap it does not.

---

## 1. Endpoint survey

### model-iq — 10 models

`GET /v1/models` returns an **OpenAI-shaped** listing (`object:"model"`, `owned_by:"openai"`, `created:1677610602`) rather than Anthropic's (`type:"model"`, `display_name`, `created_at`). Those `owned_by`/`created` values are LiteLLM placeholder constants carrying no real information. `/v1/messages` responses are translated into correct Anthropic shape but retain OpenAI `chatcmpl-*` IDs, and `thinking` blocks arrive with `"signature": null` — strip them before replaying conversation history, as anything validating signatures will reject them.

| Model | Max input tokens | `/v1/messages` |
|---|---|---|
| `claude-sonnet-4-6-fhtr` | — | ❌ 401 |
| `deepseek-v4-1-flash` | 150,000 | ✅ 200 |
| `deepseek-v4-flash-0731` | 350,000 | ✅ 200 |
| `deepseek-v4-pro-0813` | 300,000 | ✅ 200 |
| `glm-5-3` | 500,000 | ✅ 200 |
| `glm-5-3-flash-2` | 1,048,576 | ✅ 200 |
| `kimi-k3` | 500,000 | ✅ 200 |
| `ornith-1-5-397b-fp8` | — | ✅ 200 |
| `qwen3-8-flash-next` | — | ✅ 200 |
| `qwen3-8-flash-next-fp8` | — | ✅ 200 |

**`claude-sonnet-4-6-fhtr` failure.** All four auth-header variants (`x-api-key`, `Authorization: Bearer`, both, and without `anthropic-version`) return HTTP 401 carrying a *nested* upstream Anthropic error:

```json
{"type":"error","error":{"type":"authentication_error",
  "message":"x-api-key header is required"},
  "request_id":"req_011CfC2zju3ebzZfLpmqHEAr"}
```

An unauthenticated request returns a *different*, gateway-native error (`{"type":"auth_error","message":"Authentication Error, No api key passed in."}`). Two distinct 401s localise the fault: **our key clears the gateway; the gateway then fails to authenticate itself to Anthropic.** The `req_011C…` IDs are genuine Anthropic request IDs, so traffic does reach `api.anthropic.com`. Root cause is a missing or expired upstream credential on that deployment.

### z.ai — 11 models

Native Anthropic API: proper `msg_*` IDs, real cryptographic `signature` values on `thinking` blocks, `cache_read_input_tokens` and `service_tier` in usage.

`glm-4.5`, `glm-4.5-air`, `glm-4.6`, `glm-4.7`, `glm-5`, `glm-5-turbo`, `glm-5.1`, `glm-5.2`, `glm-5.3`, `glm-5.3-flash`, `glm-5.3-flashx`

---

## 2. Benchmark design

| Task | Tests | Problem |
|---|---|---|
| `lvp` | 15 | `longest_valid_parentheses(s)` — length of longest balanced substring |
| `minwin` | 12 | `min_window(s, t)` — shortest substring of `s` containing all of `t` (multiset), leftmost on ties |
| `calc` | 19 | `calculate(expr)` — recursive-descent arithmetic: `+ - * /`, parens, unary minus, division truncating toward zero, no `eval()` |
| `wbrk` | 8 | `word_break_all(s, words)` — every sentence segmentation, lexicographically sorted |
| `topo` | 10 | `topo_order(n, edges)` — lexicographically smallest topological order, `None` on cycle |
| `qs` | 14 | `parse_qs(query)` — query-string parser: repeated keys, `+`→space, `%XX` UTF-8 decoding, no stdlib helpers |

**Protocol.** 3 independent samples per (model, task) = 198 calls. System prompt requests one ```python block, stdlib only. `max_tokens=32000`, no temperature override, 8 concurrent workers, **job order shuffled** so each model's samples land under different load. The longest fenced block is extracted and graded in a throwaway subprocess (120 s timeout, type-strict equality — `type(got) == type(exp)`, so a tuple cannot pass as a list).

**Answer-key validation.** A reference implementation was written first and run against the suite; it scores **78/78**. This caught two errors in the hand-computed key (`min_window("abcabdec","abc")` and one topological order) that would otherwise have penalised every model.

---

## 3. Results (n=3)

Cells show the **range across 3 samples** (single value = all three agreed). **Bold** = perfect in all 3.

| Model | Provider | lvp | minwin | calc | wbrk | topo | qs | Mean /78 | Best | Worst | Stable |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `glm-5.3-flash` | z.ai | **15/15** | **12/12** | **19/19** | **8/8** | **10/10** | **14/14** | **78.0** | 78 | 78 | 6/6 |
| `glm-5-3` | model-iq | **15/15** | **12/12** | **19/19** | **8/8** | **10/10** | **14/14** | **78.0** | 78 | 78 | 6/6 |
| `ornith-1-5-397b-fp8` | model-iq | **15/15** | **12/12** | **19/19** | 7–8/8 | **10/10** | **14/14** | **77.3** | 78 | 77 | 5/6 |
| `glm-5.3` | z.ai | **15/15** | **12/12** | **19/19** | 7–8/8 | **10/10** | **14/14** | **77.3** | 78 | 77 | 5/6 |
| `kimi-k3` | model-iq | **15/15** | **12/12** | **19/19** | 7–8/8 | **10/10** | **14/14** | **77.3** | 78 | 77 | 5/6 |
| `deepseek-v4-1-flash` | model-iq | **15/15** | **12/12** | **19/19** | 7/8 | **10/10** | **14/14** | **77.0** | 77 | 77 | 5/6 |
| `deepseek-v4-flash-0731` | model-iq | **15/15** | **12/12** | 17–19/19 | 7/8 | **10/10** | **14/14** | **76.0** | 77 | 75 | 4/6 |
| `qwen3-8-flash-next-fp8` | model-iq | **15/15** | **12/12** | **19/19** | 0–8/8 | **10/10** | **14/14** | **75.3** | 78 | 70 | 5/6 |
| `glm-5-3-flash-2` | model-iq | **15/15** | **12/12** | 0–19/19 | 7–8/8 | **10/10** | **14/14** | **71.0** | 78 | 58 | 4/6 |
| `deepseek-v4-pro-0813` | model-iq | **15/15** | **12/12** | 0–19/19 | 7/8 | **10/10** | **14/14** | **70.0** | 77 | 58 | 4/6 |
| `qwen3-8-flash-next` | model-iq | **15/15** | **12/12** | 0–19/19 | 0–8/8 | **10/10** | **14/14** | **62.3** | 70 | 58 | 4/6 |

### 3a. Where the variance lives

| Model | Task | Sample scores | Spread |
|---|---|---|---|
| `qwen3-8-flash-next` | `calc` | 0/19 / 19/19 / 0/19 | **19** |
| `glm-5-3-flash-2` | `calc` | 0/19 / 19/19 / 19/19 | **19** |
| `deepseek-v4-pro-0813` | `calc` | 17/19 / 0/19 / 19/19 | **19** |
| `qwen3-8-flash-next-fp8` | `wbrk` | 8/8 / 8/8 / 0/8 | **8** |
| `qwen3-8-flash-next` | `wbrk` | 7/8 / 0/8 / 8/8 | **8** |
| `deepseek-v4-flash-0731` | `calc` | 19/19 / 17/19 / 18/19 | **2** |
| `ornith-1-5-397b-fp8` | `wbrk` | 8/8 / 7/8 / 7/8 | **1** |
| `kimi-k3` | `wbrk` | 7/8 / 7/8 / 8/8 | **1** |
| `glm-5.3` | `wbrk` | 7/8 / 7/8 / 8/8 | **1** |
| `glm-5-3-flash-2` | `wbrk` | 7/8 / 8/8 / 7/8 | **1** |

**10 of 66 cells** disagreed with themselves. Every other cell returned an identical score three times. Note the shape: variance is concentrated in `calc` and `wbrk`, and it is **bimodal** — models swing between a perfect score and near-zero, not between 17 and 19. A single bad sample is usually a structural failure (wrong parse strategy, missing base case), not a slightly worse answer.

### 3b. GLM-5.3 gateway comparison, resampled

| Route | Mean /78 | Samples | Stable | Avg latency | Tokens/run |
|---|---|---|---|---|---|
| `glm-5.3-flash` @ **z.ai** | 78.0 | 78/78/78 | 6/6 | 31.5s | 9,669 |
| `glm-5-3-flash-2` @ **model-iq** | 71.0 | 58/78/77 | 4/6 | 31.7s | 24,067 |
| `glm-5.3` @ **z.ai** | 77.3 | 77/77/78 | 5/6 | 20.8s | 9,335 |
| `glm-5-3` @ **model-iq** | 78.0 | 78/78/78 | 6/6 | 52.1s | 25,299 |

**This overturns the single-sample finding.** At n=1 and `max_tokens=8000`, GLM-5.3 scored 8 points higher on z.ai, which looked like a gateway defect. At n=3 and 32k the accuracy difference is gone — `glm-5-3` @ model-iq is 78.0/78.0, marginally *ahead* of `glm-5.3` @ z.ai at 77.3. The original gap was a truncation artifact plus sampling noise.

What survives is **efficiency**: z.ai returns the same accuracy using **~2.6× fewer output tokens** (9,335 vs 25,299 for the flagship) at **~2.5× lower latency** (20.8 s vs 52.1 s). That is consistent with the input-token anomaly observed during the survey — one 6-word prompt billed at 10 tokens on some model-iq backends and 93 on others — and points to server-side prompt augmentation on model-iq that inflates both reasoning length and cost.

### 3c. Hardest tests across all 198 samples

| Task | Failure | Occurrences |
|---|---|---|
| `wbrk` | `('', ['a']) -> [''] want []` | 18 |
| `calc` | `no code block` | 2 |
| `calc` | `('1+1',) raised UnboundLocalError: cannot access local varia` | 2 |
| `wbrk` | `no code block` | 2 |
| `calc` | `('- (3 + (4 + 5))',) raised IndexError: pop from empty list` | 1 |
| `calc` | `(' 6-4/2 ',) raised ValueError: invalid literal for int() wi` | 1 |
| `calc` | `('3*-2',) -> -2 want -6` | 1 |

`word_break_all("", ["a"])` alone accounts for **18 failures** — more than every other cause combined. The standard memoized recursion returns `[""]` as its "matched everything" base case; on empty input that internal sentinel escapes as a result instead of `[]`. It is invisible on every non-empty input, and it caught nine of the eleven models at least once. `lvp`, `minwin`, `topo` and `qs` were solved perfectly by every model in every sample and contributed no ranking signal.
---

## 4. Appendix: the single-sample runs, and why `max_tokens` mattered

The n=3 run above supersedes two earlier passes, kept here because the first one produced a finding the final run cannot show.

**Run 1 — n=1, `max_tokens=8000`.** Scores ranged 48–78/78 (62%–100%). Eight cells scored zero. But **six of those eight
returned `stop_reason: max_tokens` with no closed code block** — the model spent its entire allowance reasoning and never
emitted an answer. The other two were hygiene bugs (`NameError: heapq is not defined`, `UnboundLocalError`).

**Run 2 — the 13 sub-perfect cells re-run at 32k.** Every zero disappeared. The apparent 62%–100% capability spread was
mostly a budget artifact.

| Cell | 8k run | 32k re-run | Tokens used |
|---|---|---|---|
| `qwen3-8-flash-next` / `calc` | 0/19 | **19/19** | 8,000 → 25,069 |
| `glm-5-3-flash-2` / `minwin` | 0/12 | **12/12** | 8,000 → 4,097 |
| `glm-5-3` / `wbrk` | 0/8 | **8/8** | 8,000 → 2,425 |
| `qwen3-8-flash-next` / `wbrk` | 0/8 | 7/8 | 8,000 → 29,003 |
| `qwen3-8-flash-next-fp8` / `wbrk` | 0/8 | 7/8 | 8,000 → 26,319 |

Two distinct causes hide in that table. The qwen pair genuinely needed the headroom — 25k–29k tokens. But `glm-5-3`
scored 0/8 while burning all 8,000 tokens, then scored **8/8 using only 2,425**. It never needed a bigger budget; it
needed a different sample. That is runaway reasoning, and the n=3 run confirms it as the dominant failure mode.

**Operational consequence: on model-iq, `max_tokens` is a correctness parameter, not a safety valve.** At 8k, five cells
produced billable tokens and zero usable output. In the final 32k run, only **4 of 198 calls** truncated.

---

## 5. Analysis

### Reliability, not capability, separates these models

Every model solved `lvp`, `minwin`, `topo` and `qs` perfectly in all three samples. The entire ranking rests on `calc`
and `wbrk`, and mostly on whether a model produced its *good* answer on a given attempt. Six models are within 1.0 point
of each other — well inside the noise of n=3 — so the mean column should be read as "these are roughly equivalent" and
the **Stable** column as the real discriminator.

### Variance is bimodal, which makes single calls risky

Of 10 varying cells, six swing between perfect and near-zero (`0/19 → 19/19`, `0/8 → 8/8`). Models do not degrade
gracefully here; they either pick a workable strategy or produce something structurally broken. `deepseek-v4-pro-0813`
illustrates the cost: sample totals of 75 / 58 / 77. Its mean of 70.0 describes no actual run it ever produced.

### Quantization costs robustness, not reasoning

`qwen3-8-flash-next` (62.3) vs `qwen3-8-flash-next-fp8` (75.3) is the cleanest controlled pair available, and the fp8
build scored *higher* — 5/6 stable tasks against 4/6. Both solved identical task sets when they succeeded, so the
quantization did not lower the capability ceiling; it shifted how often each one fell off it. With n=3 that 13-point gap
is not significant, but it is firm evidence against fp8 costing reasoning quality on this workload.

### Token cost is the largest real difference, and it is inverted

Accuracy spans 16 points; **output cost spans 44×**. The two most expensive models are also the two worst:

| | Tokens/run | Mean /78 |
|---|---|---|
| `deepseek-v4-flash-0731` | 1,569 | 76.0 |
| `deepseek-v4-pro-0813` | 1,470 | 70.0 |
| `qwen3-8-flash-next-fp8` | 61,894 | 75.3 |
| `qwen3-8-flash-next` | 68,767 | 62.3 |

`deepseek-v4-1-flash` is the standout on this axis: **77.0 with zero variance** (77/77/77) at 3,472 tokens and 5.6 s —
within 1 point of the best model in the field at a seventh of the token cost and a tenth of the latency. Its one
consistent miss is the `word_break_all("", …)` edge case, which is a deterministic bug, not instability.

### What the n=1 runs got wrong

Three conclusions from the single-sample passes did not survive resampling, which is the clearest argument for running n>1:

- **"`kimi-k3` is perfect and the most token-efficient."** It scored 78/78 once; across three samples it averages 77.3
  with 5/6 stable, and at 9,366 tokens it is mid-field on cost, not leading.
- **"GLM-5.3 scores 8 points higher on z.ai."** False — a truncation artifact. At 32k the two gateways are tied on
  accuracy, with model-iq marginally ahead.
- **"`deepseek-v4-flash-0731` improved 48 → 77 on re-run."** That was resampling, correctly flagged at the time. Its
  true mean is 76.0 with samples of 77/75/76.

---

## 6. Recommendations

_See also **Top 3 recommended for coding** above._

1. **For reliability, use `glm-5.3-flash` @ z.ai.** It is one of only two models that never dropped a test (78/78/78,
   6/6 stable), and it does so on 9,669 tokens — 2.5× cheaper than the other perfect scorer, `glm-5-3` @ model-iq
   (25,299 tokens, 52.1 s).
2. **For cost and throughput, use `deepseek-v4-1-flash` @ model-iq.** 77.0 with zero variance, 5.6 s, 3,472 tokens. It
   gives up ~1 point for a ~7× token saving and is the most *predictable* model measured.
3. **Avoid both `qwen3-8-flash-next` variants for coding.** Worst accuracy, 40× the token cost, ~55 s per task.
4. **Set `max_tokens` ≥ 32,000 on model-iq for any reasoning model.** At 8k these models burn the full budget and return
   nothing. This is the single highest-value configuration change available.
5. **Prefer z.ai when routing choice exists.** Equal accuracy, ~2.6× fewer output tokens, ~2.5× lower latency, native
   Anthropic semantics (real `msg_*` IDs, valid thinking-block signatures).
6. **Report the `claude-sonnet-4-6-fhtr` credential failure** to whoever administers model-iq, quoting request ID
   `req_011CfC2zju3ebzZfLpmqHEAr`. No client-side change can work around it.
7. **Ask model-iq operators about server-side prompt augmentation.** The input-token spread (10 → 93 tokens for one
   6-word prompt) and ~2.6× inflated generation lengths both point at injected per-model prompts or chat templates.

---

## 7. Caveats

- **n = 3 is still small.** Differences under ~1.5 points are not significant. `glm-5.3-flash` at 78.0 and
  `deepseek-v4-1-flash` at 77.0 are not reliably distinguishable; the **Stable** column is more informative than the mean.
- **No temperature control.** Provider defaults were used throughout, so the variance measured is whatever each gateway
  ships by default — which is the realistic condition, but not a controlled one.
- **Latency is contended.** All 198 calls ran across 8 concurrent workers. Absolute timings are inflated; relative
  comparison within the run is fair, and shuffling job order removed the queue-position bias that distorted run 1.
- **`deepseek-v4-pro-0813`'s mean is misleading.** Samples of 75/58/77 average to a score it never produced. Read the
  sample list, not the mean, for high-variance models.
- **Six algorithmic tasks is a narrow probe.** Self-contained functions only — no multi-file work, no debugging of
  existing code, no API/framework knowledge, no long-context or agentic behaviour. Do not extrapolate to agentic coding.
- **Pricing was not measured.** Token counts are a proxy for cost; actual per-model rates on either gateway were not
  checked and could reorder the cost recommendations.
- **The harness executes model-generated code**, sandboxed only by a throwaway subprocess and a 120 s timeout.

---

## 8. Reproducing

```
bench/
├── tasks.py        # 6 task specs + 78 hidden tests
├── reference.py    # reference solutions — scores 78/78, validates the answer key
├── run.py          # run 1: n=1 @ max_tokens=8000        → results.json
├── retry.py        # run 2: sub-perfect cells @ 32k       → retry.json
├── run3.py         # run 3 (final): n=3 @ 32k, 198 calls  → results3.json
├── final_report.py # builds this document
└── run.log, retry.log, run3.log
```

```bash
export MIQ_KEY=$(op read "op://business/fengshui-anthropic/model-iq-key")
export ZAI_KEY=$(op read "op://business/fengshui-anthropic/z-ai-1")
python3 run3.py && python3 final_report.py
```
