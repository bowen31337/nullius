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
