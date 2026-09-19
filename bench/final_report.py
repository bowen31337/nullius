import json, collections, statistics as st, datetime
TASKS=["lvp","minwin","calc","wordbreak","topo","qs"]
TOT={"lvp":15,"minwin":12,"calc":19,"wordbreak":8,"topo":10,"qs":14}
LAB={"lvp":"lvp","minwin":"minwin","calc":"calc","wordbreak":"wbrk","topo":"topo","qs":"qs"}
DESC={"lvp":"`longest_valid_parentheses(s)` — length of longest balanced substring",
 "minwin":"`min_window(s, t)` — shortest substring of `s` containing all of `t` (multiset), leftmost on ties",
 "calc":"`calculate(expr)` — recursive-descent arithmetic: `+ - * /`, parens, unary minus, division truncating toward zero, no `eval()`",
 "wordbreak":"`word_break_all(s, words)` — every sentence segmentation, lexicographically sorted",
 "topo":"`topo_order(n, edges)` — lexicographically smallest topological order, `None` on cycle",
 "qs":"`parse_qs(query)` — query-string parser: repeated keys, `+`→space, `%XX` UTF-8 decoding, no stdlib helpers"}

R1=json.load(open("results.json")); RT=json.load(open("retry.json")); R3=json.load(open("results3.json"))
S=collections.defaultdict(list)
for r in R3: S[(r["provider"],r["model"],r["task"])].append(r)
MODELS=sorted({(r["provider"],r["model"]) for r in R3})

def samples(prov,m):
    return [sum(x["passed"] for t in TASKS for x in S[(prov,m,t)] if x["sample"]==s) for s in (1,2,3)]
def stats(prov,m):
    ps=samples(prov,m)
    stable=sum(1 for t in TASKS if all(x["passed"]==TOT[t] for x in S[(prov,m,t)]))
    lat=st.mean([x["latency"] for t in TASKS for x in S[(prov,m,t)]])
    tok=sum(x["out_tok"] or 0 for t in TASKS for x in S[(prov,m,t)])/3
    return st.mean(ps),ps,stable,lat,tok
def cellrange(prov,m,t):
    ss=sorted(x["passed"] for x in S[(prov,m,t)])
    txt=f"{ss[0]}/{TOT[t]}" if len(set(ss))==1 else f"{min(ss)}–{max(ss)}/{TOT[t]}"
    return f"**{txt}**" if all(v==TOT[t] for v in ss) else txt

rows=sorted(((stats(p,m),p,m) for p,m in MODELS), key=lambda r:(-r[0][0],-r[0][2],r[0][3]))
now=datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
L=[];A=L.append

A("# Anthropic-Compatible Gateway Benchmark")
A("")
A(f"_Final · {now} · 11 models · 6 coding tasks · 78 hidden tests · **3 samples per cell (198 calls)**_")
A("")
A("Two Anthropic-Messages-compatible gateways, surveyed and benchmarked on Python coding ability.")
A("")
A("| Gateway | Base URL | Credential |")
A("|---|---|---|")
A("| model-iq (Accenture) | `https://model-iq.aicore.accenture.com` | `op://business/fengshui-anthropic/model-iq-key` |")
A("| z.ai | `https://api.z.ai/api/anthropic` | `op://business/fengshui-anthropic/z-ai-1` |")
A("")
A("## Headline")
A("")
A("| # | Model | Provider | Mean /78 | Samples | Stable | Avg s | Tokens/run |")
A("|---|---|---|---|---|---|---|---|")
for i,((mean,ps,stable,lat,tok),prov,m) in enumerate(rows,1):
    b="**" if stable==6 else ""
    A(f'| {i} | {b}`{m}`{b} | {prov} | **{mean:.1f}** | {ps[0]}/{ps[1]}/{ps[2]} | {stable}/6 | {lat:.1f} | {tok:,.0f} |')
A("")
A("**Stable** = tasks perfect in *all three* samples — the measure of whether one call can be trusted.")
A("")
A("Three findings survive resampling:")
A("")
A("1. **Accuracy is a near-tie.** Six models sit within 1.0 point of each other (78.0 → 77.0). Only **two** never "
  "dropped a test: `glm-5.3-flash` @ z.ai and `glm-5-3` @ model-iq.")
A("2. **Cost and latency differ by ~40×, and that is the real decision.** `deepseek-v4-flash-0731` averages "
  "1,569 tokens at 1.7 s; `qwen3-8-flash-next` averages 68,767 tokens at 57.8 s **and scores 16 points lower**.")
A("3. **`claude-sonnet-4-6-fhtr` on model-iq is broken** — upstream credential failure, HTTP 401, not fixable client-side.")
A("")
A("---")
A("")
A("## 1. Endpoint survey")
A("")
A("### model-iq — 10 models")
A("")
A("`GET /v1/models` returns an **OpenAI-shaped** listing (`object:\"model\"`, `owned_by:\"openai\"`, `created:1677610602`) "
  "rather than Anthropic's (`type:\"model\"`, `display_name`, `created_at`). Those `owned_by`/`created` values are LiteLLM "
  "placeholder constants carrying no real information. `/v1/messages` responses are translated into correct Anthropic shape "
  "but retain OpenAI `chatcmpl-*` IDs, and `thinking` blocks arrive with `\"signature\": null` — strip them before replaying "
  "conversation history, as anything validating signatures will reject them.")
A("")
A("| Model | Max input tokens | `/v1/messages` |")
A("|---|---|---|")
for m,mx in [("claude-sonnet-4-6-fhtr","—"),("deepseek-v4-1-flash","150,000"),("deepseek-v4-flash-0731","350,000"),
             ("deepseek-v4-pro-0813","300,000"),("glm-5-3","500,000"),("glm-5-3-flash-2","1,048,576"),
             ("kimi-k3","500,000"),("ornith-1-5-397b-fp8","—"),("qwen3-8-flash-next","—"),("qwen3-8-flash-next-fp8","—")]:
    A(f'| `{m}` | {mx} | {"❌ 401" if m.startswith("claude") else "✅ 200"} |')
A("")
A("**`claude-sonnet-4-6-fhtr` failure.** All four auth-header variants (`x-api-key`, `Authorization: Bearer`, both, and "
  "without `anthropic-version`) return HTTP 401 carrying a *nested* upstream Anthropic error:")
A("")
A("```json")
A('{"type":"error","error":{"type":"authentication_error",')
A('  "message":"x-api-key header is required"},')
A('  "request_id":"req_011CfC2zju3ebzZfLpmqHEAr"}')
A("```")
A("")
A("An unauthenticated request returns a *different*, gateway-native error "
  "(`{\"type\":\"auth_error\",\"message\":\"Authentication Error, No api key passed in.\"}`). Two distinct 401s localise the "
  "fault: **our key clears the gateway; the gateway then fails to authenticate itself to Anthropic.** The `req_011C…` IDs "
  "are genuine Anthropic request IDs, so traffic does reach `api.anthropic.com`. Root cause is a missing or expired upstream "
  "credential on that deployment.")
A("")
A("### z.ai — 11 models")
A("")
A("Native Anthropic API: proper `msg_*` IDs, real cryptographic `signature` values on `thinking` blocks, "
  "`cache_read_input_tokens` and `service_tier` in usage.")
A("")
A("`glm-4.5`, `glm-4.5-air`, `glm-4.6`, `glm-4.7`, `glm-5`, `glm-5-turbo`, `glm-5.1`, `glm-5.2`, `glm-5.3`, `glm-5.3-flash`, `glm-5.3-flashx`")
A("")
A("---")
A("")
A("## 2. Benchmark design")
A("")
A("| Task | Tests | Problem |")
A("|---|---|---|")
for t in TASKS: A(f"| `{LAB[t]}` | {TOT[t]} | {DESC[t]} |")
A("")
A("**Protocol.** 3 independent samples per (model, task) = 198 calls. System prompt requests one ```python block, stdlib "
  "only. `max_tokens=32000`, no temperature override, 8 concurrent workers, **job order shuffled** so each model's samples "
  "land under different load. The longest fenced block is extracted and graded in a throwaway subprocess (120 s timeout, "
  "type-strict equality — `type(got) == type(exp)`, so a tuple cannot pass as a list).")
A("")
A("**Answer-key validation.** A reference implementation was written first and run against the suite; it scores **78/78**. "
  "This caught two errors in the hand-computed key (`min_window(\"abcabdec\",\"abc\")` and one topological order) that would "
  "otherwise have penalised every model.")
A("")
A("---")
A("")
A("## 3. Results (n=3)")
A("")
A("Cells show the **range across 3 samples** (single value = all three agreed). **Bold** = perfect in all 3.")
A("")
A("| Model | Provider | "+" | ".join(LAB[t] for t in TASKS)+" | Mean /78 | Best | Worst | Stable |")
A("|---|---|"+"---|"*len(TASKS)+"---|---|---|---|")
for (mean,ps,stable,lat,tok),prov,m in rows:
    cs=" | ".join(cellrange(prov,m,t) for t in TASKS)
    A(f'| `{m}` | {prov} | {cs} | **{mean:.1f}** | {max(ps)} | {min(ps)} | {stable}/6 |')
A("")
A("### 3a. Where the variance lives")
A("")
var=[]
for prov,m in MODELS:
    for t in TASKS:
        ss=[x["passed"] for x in sorted(S[(prov,m,t)],key=lambda z:z["sample"])]
        if len(set(ss))>1: var.append((max(ss)-min(ss),m,prov,t,ss))
var.sort(reverse=True)
A("| Model | Task | Sample scores | Spread |")
A("|---|---|---|---|")
for sp,m,prov,t,ss in var:
    A(f'| `{m}` | `{LAB[t]}` | {" / ".join(f"{v}/{TOT[t]}" for v in ss)} | **{sp}** |')
A("")
A(f"**{len(var)} of {len(MODELS)*len(TASKS)} cells** disagreed with themselves. Every other cell returned an identical "
  "score three times. Note the shape: variance is concentrated in `calc` and `wbrk`, and it is **bimodal** — models swing "
  "between a perfect score and near-zero, not between 17 and 19. A single bad sample is usually a structural failure "
  "(wrong parse strategy, missing base case), not a slightly worse answer.")
A("")
A("### 3b. GLM-5.3 gateway comparison, resampled")
A("")
A("| Route | Mean /78 | Samples | Stable | Avg latency | Tokens/run |")
A("|---|---|---|---|---|---|")
for key in [("z.ai","glm-5.3-flash"),("model-iq","glm-5-3-flash-2"),("z.ai","glm-5.3"),("model-iq","glm-5-3")]:
    mean,ps,stable,lat,tok=stats(*key)
    A(f'| `{key[1]}` @ **{key[0]}** | {mean:.1f} | {ps[0]}/{ps[1]}/{ps[2]} | {stable}/6 | {lat:.1f}s | {tok:,.0f} |')
A("")
A("**This overturns the single-sample finding.** At n=1 and `max_tokens=8000`, GLM-5.3 scored 8 points higher on z.ai, "
  "which looked like a gateway defect. At n=3 and 32k the accuracy difference is gone — `glm-5-3` @ model-iq is 78.0/78.0, "
  "marginally *ahead* of `glm-5.3` @ z.ai at 77.3. The original gap was a truncation artifact plus sampling noise.")
A("")
A("What survives is **efficiency**: z.ai returns the same accuracy using **~2.6× fewer output tokens** "
  "(9,335 vs 25,299 for the flagship) at **~2.5× lower latency** (20.8 s vs 52.1 s). That is consistent with the "
  "input-token anomaly observed during the survey — one 6-word prompt billed at 10 tokens on some model-iq backends and "
  "93 on others — and points to server-side prompt augmentation on model-iq that inflates both reasoning length and cost.")
A("")
A("### 3c. Hardest tests across all 198 samples")
A("")
errs=collections.Counter()
for r in R3:
    if r.get("err") and r["passed"]<TOT[r["task"]]: errs[(r["task"],r["err"][:60])]+=1
A("| Task | Failure | Occurrences |")
A("|---|---|---|")
for (t,e),c in errs.most_common(8):
    A(f'| `{LAB[t]}` | `{e.replace("|","\\|")}` | {c} |')
A("")
A("`word_break_all(\"\", [\"a\"])` alone accounts for **18 failures** — more than every other cause combined. "
  "The standard memoized recursion returns `[\"\"]` as its \"matched everything\" base case; on empty input that internal "
  "sentinel escapes as a result instead of `[]`. It is invisible on every non-empty input, and it caught nine of the "
  "eleven models at least once. `lvp`, `minwin`, `topo` and `qs` were solved perfectly by every model in every sample "
  "and contributed no ranking signal.")
A("")
open("FINAL_A.md","w").write("\n".join(L)); print("part A:",len(L),"lines")
