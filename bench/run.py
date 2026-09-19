import json, os, re, subprocess, sys, tempfile, time, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tasks import TASKS

BASE = os.path.dirname(os.path.abspath(__file__))
MIQ = ("https://model-iq.aicore.accenture.com", os.environ["MIQ_KEY"])
ZAI = ("https://api.z.ai/api/anthropic", os.environ["ZAI_KEY"])

MODELS = [
    ("deepseek-v4-1-flash",    MIQ, "model-iq"),
    ("deepseek-v4-flash-0731", MIQ, "model-iq"),
    ("deepseek-v4-pro-0813",   MIQ, "model-iq"),
    ("glm-5-3",                MIQ, "model-iq"),
    ("glm-5-3-flash-2",        MIQ, "model-iq"),
    ("kimi-k3",                MIQ, "model-iq"),
    ("ornith-1-5-397b-fp8",    MIQ, "model-iq"),
    ("qwen3-8-flash-next",     MIQ, "model-iq"),
    ("qwen3-8-flash-next-fp8", MIQ, "model-iq"),
    ("glm-5.3",                ZAI, "z.ai"),
    ("glm-5.3-flash",          ZAI, "z.ai"),
]

SYS = ("You are an expert Python programmer. Respond with ONE ```python code block "
       "containing the complete function and any helpers. No explanation outside the block. "
       "Use only the Python standard library.")

def call(model, endpoint, prompt, max_tokens=8000, retries=3):
    base, key = endpoint
    body = json.dumps({"model": model, "max_tokens": max_tokens, "system": SYS,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    last = None
    for attempt in range(retries):
        req = urllib.request.Request(base + "/v1/messages", data=body, headers={
            "x-api-key": key, "anthropic-version": "2023-06-01",
            "content-type": "application/json"})
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                d = json.loads(r.read())
            txt = "".join(b.get("text", "") for b in d.get("content", []) if b.get("type") == "text")
            return {"ok": True, "text": txt, "latency": time.time() - t0,
                    "out_tok": d.get("usage", {}).get("output_tokens"),
                    "in_tok": d.get("usage", {}).get("input_tokens"),
                    "stop": d.get("stop_reason"),
                    "thinking": any(b.get("type") == "thinking" for b in d.get("content", []))}
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
            if isinstance(e, urllib.error.HTTPError):
                try: last += " | " + e.read()[:300].decode()
                except Exception: pass
            time.sleep(2 * (attempt + 1))
    return {"ok": False, "error": last, "latency": 0, "out_tok": 0, "stop": None, "thinking": False}

def extract(text):
    blocks = re.findall(r"```(?:python|py)?\s*\n(.*?)```", text, re.S)
    if blocks:
        return max(blocks, key=len)
    return text if "def " in text else ""

HARNESS = r'''
import json, sys
sys.setrecursionlimit(100000)
sys.path.insert(0, %r)
from tasks import TASKS
name = %r
t = TASKS[name]
import solution
f = getattr(solution, t["fn"], None)
if f is None:
    print(json.dumps({"passed":0,"total":len(t["tests"]),"err":"missing function "+t["fn"]})); sys.exit()
p = 0; firstfail = None
for args, exp in t["tests"]:
    a = args if isinstance(args, tuple) else (args,)
    try:
        got = f(*[x[:] if isinstance(x, list) else x for x in a])
        if got == exp and type(got) == type(exp): p += 1
        elif firstfail is None: firstfail = f"{a!r} -> {got!r} want {exp!r}"
    except Exception as e:
        if firstfail is None: firstfail = f"{a!r} raised {type(e).__name__}: {e}"
print(json.dumps({"passed":p,"total":len(t["tests"]),"err":firstfail}))
'''

def grade(name, code):
    if not code.strip():
        return {"passed": 0, "total": len(TASKS[name]["tests"]), "err": "no code block"}
    with tempfile.TemporaryDirectory() as d:
        open(os.path.join(d, "solution.py"), "w").write(code)
        open(os.path.join(d, "h.py"), "w").write(HARNESS % (BASE, name))
        try:
            r = subprocess.run([sys.executable, "h.py"], cwd=d, capture_output=True,
                               text=True, timeout=120)
        except subprocess.TimeoutExpired:
            return {"passed": 0, "total": len(TASKS[name]["tests"]), "err": "TIMEOUT(120s)"}
        try:
            return json.loads(r.stdout.strip().splitlines()[-1])
        except Exception:
            return {"passed": 0, "total": len(TASKS[name]["tests"]),
                    "err": "harness error: " + (r.stderr[-200:] or r.stdout[-200:])}

def job(args):
    model, ep, provider, tname = args
    res = call(model, ep, TASKS[tname]["prompt"])
    if not res["ok"]:
        out = {"passed": 0, "total": len(TASKS[tname]["tests"]), "err": res["error"]}
    else:
        out = grade(tname, extract(res["text"]))
    rec = {"model": model, "provider": provider, "task": tname,
           "latency": round(res["latency"], 2), "out_tok": res["out_tok"],
           "stop": res["stop"], "thinking": res["thinking"], **out}
    print(f'{provider:8} {model:24} {tname:10} {rec["passed"]}/{rec["total"]} '
          f'{rec["latency"]:6.1f}s tok={rec["out_tok"]} {(rec["err"] or "")[:60]}', flush=True)
    return rec

jobs = [(m, ep, p, t) for (m, ep, p) in MODELS for t in TASKS]
print(f"running {len(jobs)} calls...", flush=True)
with ThreadPoolExecutor(max_workers=8) as ex:
    results = list(ex.map(job, jobs))
json.dump(results, open(os.path.join(BASE, "results.json"), "w"), indent=1)
print("WROTE results.json")
