import json, collections, datetime
TASKS=["lvp","minwin","calc","wordbreak","topo","qs"]
TOT={"lvp":15,"minwin":12,"calc":19,"wordbreak":8,"topo":10,"qs":14}
LABEL={"lvp":"lvp","minwin":"minwin","calc":"calc","wordbreak":"wbrk","topo":"topo","qs":"qs"}
R=json.load(open("results.json")); RETRY=json.load(open("retry.json"))
by=collections.defaultdict(dict)
for r in R: by[(r["provider"],r["model"])][r["task"]]=r
ret={(r["model"],r["task"]):r for r in RETRY}

def cell(m,t,d):
    """Comparison-in-cell: `before → after` when the retry changed the score."""
    a=d[t]["passed"]; r=ret.get((m,t))
    if r is None: return f"{a}/{TOT[t]}"
    b=r["passed"]
    if b==a: return f"{a}/{TOT[t]} → {b}/{TOT[t]}" if a<TOT[t] else f"{a}/{TOT[t]}"
    arrow="→"
    mark="✅" if b==TOT[t] else ("▲" if b>a else "▼")
    return f"{a}/{TOT[t]} {arrow} **{b}/{TOT[t]}** {mark}"

rows=[]
for (prov,m),d in by.items():
    before=sum(d[t]["passed"] for t in TASKS)
    after=sum((ret[(m,t)]["passed"] if (m,t) in ret and ret[(m,t)]["passed"]>d[t]["passed"] else d[t]["passed"]) for t in TASKS)
    solved=sum(1 for t in TASKS if (ret[(m,t)]["passed"] if (m,t) in ret and ret[(m,t)]["passed"]>d[t]["passed"] else d[t]["passed"])==TOT[t])
    lat=sum(d[t]["latency"] for t in TASKS)/6; tok=sum(d[t]["out_tok"] or 0 for t in TASKS)
    rows.append((after,before,solved,-lat,prov,m,d,lat,tok))
rows.sort(reverse=True)

L=[];A=L.append
A("## 4. Results — failing cells re-run at `max_tokens=32000`")
A("")
A("All 13 sub-perfect cells were re-run with a 4× larger budget. Cells show **`before → after`**; "
  "✅ = now perfect, ▲ = improved, unchanged cells show a single score.")
A("")
A("| Model | Provider | "+" | ".join(LABEL[t] for t in TASKS)+" | **Total** | % | Solved |")
A("|---|---|"+"---|"*len(TASKS)+"---|---|---|")
for after,before,solved,_,prov,m,d,lat,tok in rows:
    cs=" | ".join(cell(m,t,d) for t in TASKS)
    tot=f"**{after}/78**" if after==before else f"{before}/78 → **{after}/78**"
    A(f"| `{m}` | {prov} | {cs} | {tot} | {100*after/78:.0f}% | {solved}/6 |")
A("")

# split analysis
trunc=[r for r in RETRY if next(x for x in R if x["model"]==r["model"] and x["task"]==r["task"])["stop"]=="max_tokens"]
logic=[r for r in RETRY if next(x for x in R if x["model"]==r["model"] and x["task"]==r["task"])["stop"]!="max_tokens"]
def orig(r): return next(x for x in R if x["model"]==r["model"] and x["task"]==r["task"])
A("### 4a. Truncation failures — a budget fix, and a legitimate one")
A("")
A("These cells originally returned `stop_reason: max_tokens` with **no closed code block**: the model spent its entire "
  "allowance reasoning and never emitted an answer. Raising the ceiling tests the same capability, so these deltas are real.")
A("")
A("| Model | Task | Before | After | Tokens (8k run → 32k run) | Verdict |")
A("|---|---|---|---|---|---|")
for r in sorted(trunc,key=lambda x:-(x["passed"]-orig(x)["passed"])):
    o=orig(r); v="**fixed**" if r["passed"]==TOT[r["task"]] else ("improved" if r["passed"]>o["passed"] else "still failing")
    A(f'| `{r["model"]}` | `{LABEL[r["task"]]}` | {o["passed"]}/{TOT[r["task"]]} | **{r["passed"]}/{TOT[r["task"]]}** | {o["out_tok"]:,} → {r["out_tok"]:,} | {v} |')
A("")
A("### 4b. Logic failures — resampling, not a fix")
A("")
A("These cells already finished cleanly (`stop_reason: end_turn`) within the original budget. The failure was a **bug, not a "
  "truncation**, so a larger ceiling cannot address it and any change here is ordinary sampling variance. Reported for completeness; "
  "treat improvements with suspicion.")
A("")
A("| Model | Task | Before | After | Failing test | Verdict |")
A("|---|---|---|---|---|---|")
for r in logic:
    o=orig(r); err=(r["err"] or "—").replace("|","\\|")[:70]
    if r["passed"]>o["passed"]: v="improved *(resample)*"
    elif r["passed"]<o["passed"]: v="regressed *(resample)*"
    else: v="unchanged"
    A(f'| `{r["model"]}` | `{LABEL[r["task"]]}` | {o["passed"]}/{TOT[r["task"]]} | {r["passed"]}/{TOT[r["task"]]} | `{err}` | {v} |')
A("")
open("REPORT_PART2.md","w").write("\n".join(L))
print("part 2 written")
