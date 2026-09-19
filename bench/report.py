import json, collections, datetime

TASKS = ["lvp","minwin","calc","wordbreak","topo","qs"]
TOT = {"lvp":15,"minwin":12,"calc":19,"wordbreak":8,"topo":10,"qs":14}
LABEL = {"lvp":"lvp","minwin":"minwin","calc":"calc","wordbreak":"wbrk","topo":"topo","qs":"qs"}
DESC = {
 "lvp":"`longest_valid_parentheses(s)` — length of longest balanced substring",
 "minwin":"`min_window(s, t)` — shortest substring of `s` containing all of `t` (multiset), leftmost on ties",
 "calc":"`calculate(expr)` — recursive-descent arithmetic: `+ - * /`, parens, unary minus, division truncating toward zero, no `eval()`",
 "wordbreak":"`word_break_all(s, words)` — every sentence segmentation, lexicographically sorted",
 "topo":"`topo_order(n, edges)` — lexicographically smallest topological order, `None` on cycle",
 "qs":"`parse_qs(query)` — query-string parser: repeated keys, `+`→space, `%XX` UTF-8 decoding, no stdlib helpers",
}
PROV = {"model-iq":"model-iq","z.ai":"z.ai"}

R = json.load(open("results.json"))
try:
    RETRY = json.load(open("retry.json"))
except FileNotFoundError:
    RETRY = []

by = collections.defaultdict(dict)
for r in R: by[(r["provider"], r["model"])][r["task"]] = r
ret = {(r["model"], r["task"]): r for r in RETRY}

def table(cells, title):
    rows = []
    for (prov, m), d in cells.items():
        p = sum(d[t]["passed"] for t in TASKS)
        solved = sum(1 for t in TASKS if d[t]["passed"] == TOT[t])
        lat = sum(d[t]["latency"] for t in TASKS)/6
        tok = sum(d[t]["out_tok"] or 0 for t in TASKS)
        rows.append((p, solved, -lat, prov, m, d, lat, tok))
    rows.sort(reverse=True)
    out = [title, "",
           "| Model | Provider | " + " | ".join(LABEL[t] for t in TASKS) + " | **Total** | % | Solved | Avg s | Out tok |",
           "|---|---|" + "---|"*len(TASKS) + "---|---|---|---|---|"]
    for p, solved, _, prov, m, d, lat, tok in rows:
        cs = []
        for t in TASKS:
            v = d[t]["passed"]; cell = f'{v}/{TOT[t]}'
            cs.append(f"**{cell}**" if v == 0 else cell)
        bold = "**" if p == 78 else ""
        out.append(f'| {bold}`{m}`{bold} | {prov} | ' + " | ".join(cs) +
                   f' | **{p}/78** | {100*p/78:.0f}% | {solved}/6 | {lat:.1f} | {tok:,} |')
    return "\n".join(out), rows

base_tbl, base_rows = table(by, "")

# merged (best-of) table using retry results
merged = collections.defaultdict(dict)
for (prov, m), d in by.items():
    for t in TASKS:
        r = ret.get((m, t))
        merged[(prov, m)][t] = r if (r and r["passed"] > d[t]["passed"]) else d[t]
merged_tbl, merged_rows = table(merged, "")

now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

L = []
A = L.append
A("# Anthropic-Compatible Gateway Benchmark")
A("")
A(f"_Generated {now} · 11 models · 6 coding tasks · 78 hidden tests_")
A("")
A("Two Anthropic-Messages-compatible gateways were surveyed and benchmarked on Python coding ability:")
A("")
A("| Gateway | Base URL | Credential |")
A("|---|---|---|")
A("| model-iq (Accenture) | `https://model-iq.aicore.accenture.com` | `op://business/fengshui-anthropic/model-iq-key` |")
A("| z.ai | `https://api.z.ai/api/anthropic` | `op://business/fengshui-anthropic/z-ai-1` |")
A("")
A("---")
A("")
A("## 1. Endpoint survey")
A("")
A("### model-iq — 10 models advertised")
A("")
A("`GET /v1/models` returns an **OpenAI-shaped** listing (`object:\"model\"`, `owned_by:\"openai\"`, `created:1677610602`) rather than Anthropic's "
  "(`type:\"model\"`, `display_name`, `created_at`). The `owned_by` and `created` values are LiteLLM placeholder constants and carry no real information.")
A("")
A("| Model | Max input tokens | `/v1/messages` |")
A("|---|---|---|")
for m, mx in [("claude-sonnet-4-6-fhtr","—"),("deepseek-v4-1-flash","150,000"),("deepseek-v4-flash-0731","350,000"),
              ("deepseek-v4-pro-0813","300,000"),("glm-5-3","500,000"),("glm-5-3-flash-2","1,048,576"),
              ("kimi-k3","500,000"),("ornith-1-5-397b-fp8","—"),("qwen3-8-flash-next","—"),("qwen3-8-flash-next-fp8","—")]:
    status = "❌ 401" if m.startswith("claude") else "✅ 200"
    A(f"| `{m}` | {mx} | {status} |")
A("")
A("**`claude-sonnet-4-6-fhtr` is broken.** All four auth-header variants (`x-api-key`, `Authorization: Bearer`, both, and without "
  "`anthropic-version`) return HTTP 401 carrying a *nested* upstream Anthropic error:")
A("")
A("```json")
A('{"type":"error","error":{"type":"authentication_error",')
A(' "message":"x-api-key header is required"},')
A(' "request_id":"req_011CfC2zju3ebzZfLpmqHEAr"}')
A("```")
A("")
A("An unauthenticated request returns a *different*, gateway-native error (`{\"type\":\"auth_error\",\"message\":\"Authentication Error, No api key passed in.\"}`). "
  "The two distinct 401s localise the fault: **our key clears the gateway, and the gateway then fails to authenticate itself to Anthropic.** "
  "The `req_011C…` IDs are genuine Anthropic request IDs, confirming traffic reaches `api.anthropic.com`. "
  "Root cause is a missing or expired upstream credential on that deployment — not fixable client-side. "
  "The router message `Received Model Group=claude-sonnet-4-6-fhtr / Available Model Group Fallbacks=None` is LiteLLM vocabulary.")
A("")
A("### z.ai — 11 models advertised")
A("")
A("Native Anthropic API: proper `msg_*` IDs, real cryptographic `signature` values on `thinking` blocks, `cache_read_input_tokens` and `service_tier` in usage.")
A("")
A("`glm-4.5`, `glm-4.5-air`, `glm-4.6`, `glm-4.7`, `glm-5`, `glm-5-turbo`, `glm-5.1`, `glm-5.2`, `glm-5.3`, `glm-5.3-flash`, `glm-5.3-flashx`")
A("")
A("---")
A("")
A("## 2. Benchmark design")
A("")
A("Six algorithmic tasks, each graded by a hidden suite run in a throwaway subprocess (120 s timeout, type-strict equality):")
A("")
A("| Task | Tests | Problem |")
A("|---|---|---|")
for t in TASKS:
    A(f"| `{LABEL[t]}` | {TOT[t]} | {DESC[t]} |")
A("")
A("**Protocol.** One call per (model, task). System prompt requests a single ```python block, stdlib only. "
  "`max_tokens=8000`, no temperature override, 8 concurrent workers. The longest fenced block is extracted and graded.")
A("")
A("**Answer-key validation.** A reference implementation of all six functions was written first and run against the suite; "
  "it scores **78/78**. This caught two errors in the hand-computed key (`min_window(\"abcabdec\",\"abc\")` and one topological order) "
  "that would otherwise have penalised every model.")
A("")
A("---")
A("")
A("## 3. Results — initial run (`max_tokens=8000`)")
A("")
A(base_tbl)
A("")
A("### Same model, two gateways")
A("")
A("Both gateways serve GLM-5.3, making this a controlled comparison of routing rather than weights:")
A("")
A("| Route | Total | Avg latency | Output tokens |")
A("|---|---|---|---|")
for key in [("z.ai","glm-5.3"),("model-iq","glm-5-3"),("z.ai","glm-5.3-flash"),("model-iq","glm-5-3-flash-2")]:
    d = by[key]; p = sum(d[t]["passed"] for t in TASKS)
    A(f'| `{key[1]}` @ **{key[0]}** | {p}/78 | {sum(d[t]["latency"] for t in TASKS)/6:.1f}s | {sum(d[t]["out_tok"] or 0 for t in TASKS):,} |')
A("")
A("GLM-5.3 scored **8 points higher and ran 3.8× faster** on z.ai. Every model-iq GLM loss was `stop_reason: max_tokens` at exactly "
  "8,000 tokens with no closed code block — the model exhausted its budget reasoning and never emitted an answer. "
  "The same model finished all six tasks in 6,481 tokens on z.ai. Combined with the input-token anomaly (10 vs 93 tokens for one "
  "6-word prompt across backends), this suggests model-iq injects per-model system prompts or chat templates that inflate generation length.")
A("")
open("REPORT_PART1.md","w").write("\n".join(L))
print("part 1 written,", len(L), "lines")
