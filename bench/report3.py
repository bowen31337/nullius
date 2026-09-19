import json, collections
TASKS=["lvp","minwin","calc","wordbreak","topo","qs"]
TOT={"lvp":15,"minwin":12,"calc":19,"wordbreak":8,"topo":10,"qs":14}
R=json.load(open("results.json")); RETRY=json.load(open("retry.json"))
by=collections.defaultdict(dict)
for r in R: by[(r["provider"],r["model"])][r["task"]]=r
ret={(r["model"],r["task"]):r for r in RETRY}
def best(m,t,d): 
    r=ret.get((m,t)); return max(d[t]["passed"], r["passed"]) if r else d[t]["passed"]
rows=[]
for (prov,m),d in by.items():
    a=sum(best(m,t,d) for t in TASKS); b=sum(d[t]["passed"] for t in TASKS)
    lat=sum(d[t]["latency"] for t in TASKS)/6; tok=sum(d[t]["out_tok"] or 0 for t in TASKS)
    rows.append((a,b,-lat,prov,m,lat,tok))
rows.sort(reverse=True)
L=[];A=L.append
A("---")
A("")
A("## 5. Final standings (best of both runs)")
A("")
A("| # | Model | Provider | Score | % | Avg latency | Out tokens | Note |")
A("|---|---|---|---|---|---|---|---|")
NOTE={
 "kimi-k3":"perfect first try, most token-efficient",
 "glm-5.3":"perfect first try",
 "ornith-1-5-397b-fp8":"perfect first try",
 "qwen3-8-flash-next":"needed 25k+ tokens to reach it",
 "qwen3-8-flash-next-fp8":"needed 25k+ tokens to reach it",
 "glm-5-3":"truncation-limited at 8k",
 "glm-5-3-flash-2":"truncation-limited at 8k",
 "deepseek-v4-1-flash":"fast; misses empty-input edge case",
 "glm-5.3-flash":"slow; misses empty-input edge case",
 "deepseek-v4-flash-0731":"fastest overall; brittle first draft",
 "deepseek-v4-pro-0813":"cheapest; unary-minus bug persists",
}
for i,(a,b,_,prov,m,lat,tok) in enumerate(rows,1):
    A(f"| {i} | `{m}` | {prov} | **{a}/78** | {100*a/78:.0f}% | {lat:.1f}s | {tok:,} | {NOTE.get(m,'')} |")
A("")
open("REPORT_PART3.md","w").write("\n".join(L))
print("part3 ok")
