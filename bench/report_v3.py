import json, collections, statistics as st, datetime
TASKS=["lvp","minwin","calc","wordbreak","topo","qs"]
TOT={"lvp":15,"minwin":12,"calc":19,"wordbreak":8,"topo":10,"qs":14}
LAB={"lvp":"lvp","minwin":"minwin","calc":"calc","wordbreak":"wbrk","topo":"topo","qs":"qs"}
R=json.load(open("results3.json"))
S=collections.defaultdict(list)                      # (prov,model,task) -> [recs]
for r in R: S[(r["provider"],r["model"],r["task"])].append(r)

models=sorted({(r["provider"],r["model"]) for r in R})
def cell(prov,m,t):
    ss=sorted(x["passed"] for x in S[(prov,m,t)])
    if not ss: return "—",0,0
    perfect=sum(1 for v in ss if v==TOT[t])
    if len(set(ss))==1:
        txt=f"{ss[0]}/{TOT[t]}"
    else:
        txt=f"{min(ss)}–{max(ss)}/{TOT[t]}"
    if perfect==3: txt=f"**{txt}**"
    elif perfect==0 and max(ss)==0: txt=f"**{txt}**"
    return txt, st.mean(ss), perfect

rows=[]
for prov,m in models:
    means=[];perf=0;allp=0
    for t in TASKS:
        _,mu,p=cell(prov,m,t); means.append(mu); perf+=p; allp+= (1 if p==3 else 0)
    mean_tot=sum(means)
    lats=[x["latency"] for t in TASKS for x in S[(prov,m,t)]]
    toks=[x["out_tok"] or 0 for t in TASKS for x in S[(prov,m,t)]]
    # per-sample totals for spread
    per_sample=[]
    for s in (1,2,3):
        v=0
        for t in TASKS:
            rec=[x for x in S[(prov,m,t)] if x["sample"]==s]
            if rec: v+=rec[0]["passed"]
        per_sample.append(v)
    rows.append(dict(prov=prov,m=m,mean=mean_tot,per_sample=per_sample,
                     best=max(per_sample),worst=min(per_sample),
                     tasks_always_perfect=allp,perfect_cells=perf,
                     lat=st.mean(lats) if lats else 0,tok=sum(toks)/3))
rows.sort(key=lambda r:(-r["mean"],-r["tasks_always_perfect"],r["lat"]))

L=[];A=L.append
A("## 10. Three-sample re-run (n=3, `max_tokens=32000`)")
A("")
A("The single-sample runs above could not separate capability from sampling luck. This run draws **3 independent "
  "samples per (model, task)** — 198 calls — at a budget large enough that truncation is no longer a factor. "
  "Job order was shuffled so each model's samples land under different load, and 429s back off 20 s × attempt.")
A("")
A("Cells show the **range across 3 samples** (a single value = all three agreed). **Bold** = perfect in all 3.")
A("")
A("| Model | Provider | "+" | ".join(LAB[t] for t in TASKS)+" | Mean /78 | Best | Worst | Stable tasks |")
A("|---|---|"+"---|"*len(TASKS)+"---|---|---|---|")
for r in rows:
    cs=" | ".join(cell(r["prov"],r["m"],t)[0] for t in TASKS)
    A(f'| `{r["m"]}` | {r["prov"]} | {cs} | **{r["mean"]:.1f}** | {r["best"]} | {r["worst"]} | {r["tasks_always_perfect"]}/6 |')
A("")
A("**Mean /78** averages the three sample totals — the honest expected score for one attempt. "
  "**Stable tasks** counts tasks solved perfectly in *all three* samples: the measure of whether you can rely on a single call.")
A("")

# consistency / variance
A("### 10a. Where the variance lives")
A("")
A("| Model | Task | Sample scores | Spread |")
A("|---|---|---|---|")
var=[]
for prov,m in models:
    for t in TASKS:
        ss=[x["passed"] for x in sorted(S[(prov,m,t)],key=lambda z:z["sample"])]
        if len(set(ss))>1: var.append((max(ss)-min(ss),m,prov,t,ss))
var.sort(reverse=True)
for sp,m,prov,t,ss in var:
    A(f'| `{m}` | `{LAB[t]}` | {" / ".join(f"{v}/{TOT[t]}" for v in ss)} | **{sp}** |')
if not var: A("| — | — | all cells identical across samples | 0 |")
A("")
A(f"**{len(var)} of {len(models)*len(TASKS)} cells** varied across samples. "
  "Cells absent from this table returned the identical score all three times.")
A("")

# glm head to head
A("### 10b. GLM-5.3 gateway comparison, resampled")
A("")
A("| Route | Mean /78 | Best | Worst | Avg latency | Avg out tokens |")
A("|---|---|---|---|---|---|")
for key in [("z.ai","glm-5.3"),("model-iq","glm-5-3"),("z.ai","glm-5.3-flash"),("model-iq","glm-5-3-flash-2")]:
    r=next(x for x in rows if (x["prov"],x["m"])==key)
    A(f'| `{key[1]}` @ **{key[0]}** | {r["mean"]:.1f} | {r["best"]} | {r["worst"]} | {r["lat"]:.1f}s | {r["tok"]:,.0f} |')
A("")
# hardest tests
A("### 10c. Hardest tests across all 198 samples")
A("")
errs=collections.Counter()
for r in R:
    if r["err"] and r["passed"]<TOT[r["task"]]: errs[(r["task"],r["err"][:60])]+=1
A("| Task | Failure | Occurrences |")
A("|---|---|---|")
for (t,e),c in errs.most_common(10):
    A(f'| `{LAB[t]}` | `{e.replace("|","\\|")}` | {c} |')
A("")
open("REPORT_V3.md","w").write("\n".join(L))
print("v3 section written;", len(rows),"models,",len(var),"varying cells")
