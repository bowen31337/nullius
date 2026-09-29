#!/usr/bin/env bash
# Full browser sweep of docs/user-journeys (J1-J14).
#
# Usage: docs/user-journeys/run_sweep.sh <run-name> <scratch-dir>
#   e.g. docs/user-journeys/run_sweep.sh run-4 /tmp/sweep
#
# Every precondition comes from shipped commands: the store and the demo
# sidecar from `python -m nullius_api.demo`, the API from
# `python -m nullius_api`, the dashboard from `streamlit run` at the repo root
# (so .streamlit/config.toml applies). Needs browser-harness and the
# Playwright Chromium under ~/.pw-browsers. Screenshots go to
# docs/user-journeys/screenshots/<run-name>/; call results are printed as
# JSON lines and kept in <scratch-dir>/results.jsonl.
set -euo pipefail

RUN="${1:?run name, e.g. run-4}"
SCRATCH="${2:?scratch directory}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT="$REPO/docs/user-journeys/screenshots/$RUN"
export UV_CACHE_DIR="${UV_CACHE_DIR:-$SCRATCH/uvc}"
CHROME="${CHROME:-$HOME/.pw-browsers/chromium-1234/chrome-linux64/chrome}"
export BU_CDP_URL=http://localhost:9222

mkdir -p "$SCRATCH" "$OUT"
cd "$REPO"
PIDS=()
cleanup() { for p in "${PIDS[@]:-}"; do kill "$p" 2>/dev/null || true; done; }
trap cleanup EXIT

wait_http() { for _ in $(seq 1 90); do curl -s -o /dev/null "$1" && return 0; sleep 1; done; echo "timeout: $1" >&2; return 1; }

# Browser (headless; --no-sandbox because AppArmor blocks user namespaces).
if ! curl -s localhost:9222/json/version >/dev/null; then
  "$CHROME" --headless=new --no-sandbox --remote-debugging-port=9222 \
    --user-data-dir="$SCRATCH/chrome-profile" --no-first-run about:blank >"$SCRATCH/chrome.log" 2>&1 &
  PIDS+=($!); wait_http http://localhost:9222/json/version
fi

# Store, demo sidecar and tokens.
rm -rf "$SCRATCH/store" && mkdir -p "$SCRATCH/store"
DATABASE_URL="sqlite:///$SCRATCH/store/demo.db" uv run --all-packages python -m nullius_api.demo >"$SCRATCH/seed.log"
grep -E '^\s*export NULL_SIDECAR_' "$SCRATCH/seed.log" | sed 's/^\s*//' >"$SCRATCH/sidecar.env"
python3 - "$SCRATCH" <<'PY'
import json, secrets, sys
d = sys.argv[1]
t = {s: [secrets.token_urlsafe(24)] for s in ("metrics:read", "research", "evaluator", "risk")}
open(f"{d}/tokens.json", "w").write(json.dumps(t))
open(f"{d}/tokens-flat.json", "w").write(json.dumps({k: v[0] for k, v in t.items()}))
PY
chmod 600 "$SCRATCH/tokens.json" "$SCRATCH/sidecar.env"
DB="sqlite:///$SCRATCH/store/demo.db"

# API with engine + sidecar (8765) and without engine (8766).
( set -a; . "$SCRATCH/sidecar.env"; set +a
  DATABASE_URL="$DB" NULLIUS_API_TOKENS_FILE="$SCRATCH/tokens.json" \
  NULLIUS_EXECUTION_ENGINE=nullius_api.demo:PAPER_ENGINE \
  exec uv run --all-packages python -m nullius_api --port 8765 ) >"$SCRATCH/api.log" 2>&1 &
PIDS+=($!)
DATABASE_URL="$DB" NULLIUS_API_TOKENS_FILE="$SCRATCH/tokens.json" \
  uv run --all-packages python -m nullius_api --port 8766 >"$SCRATCH/api-noengine.log" 2>&1 &
PIDS+=($!)

# Dashboards: demo store (8501), with threshold (8502), empty (8503), no DATABASE_URL (8504).
st() { uv run --all-packages --with streamlit streamlit run packages/ops/src/ops/dashboard.py --server.port "$1"; }
DATABASE_URL="$DB" st 8501 >"$SCRATCH/st1.log" 2>&1 & PIDS+=($!)
NULLIUS_FEED_STALENESS_THRESHOLD_S=60 DATABASE_URL="$DB" st 8502 >"$SCRATCH/st2.log" 2>&1 & PIDS+=($!)
DATABASE_URL="sqlite:///$SCRATCH/store/empty.db" st 8503 >"$SCRATCH/st3.log" 2>&1 & PIDS+=($!)
env -u DATABASE_URL bash -c "$(declare -f st); st 8504" >"$SCRATCH/st4.log" 2>&1 & PIDS+=($!)
wait_http http://127.0.0.1:8765/healthz; wait_http http://127.0.0.1:8766/healthz
for p in 8501 8502 8503 8504; do wait_http "http://127.0.0.1:$p/_stcore/health"; done
head -1 "$SCRATCH/api.log"
ss -ltn | grep -E ':(8765|8766|850[1-4]) ' | awk '{print "listening", $4}'

# Dashboard journeys (J1-J7).
OUT="$OUT" timeout 300 browser-harness <<'PY' | grep -v -E 'update available|agents:' | tee "$SCRATCH/dashboard.txt"
import os, json
out = os.environ["OUT"]
for name, port, marker in [("J2-J4-J5-J6-dashboard-populated", 8501, "FDR_deploy"),
                           ("J4-lamps-with-threshold", 8502, "FDR_deploy"),
                           ("J1-dashboard-empty-db", 8503, "FDR_deploy"),
                           ("J3-dashboard-no-database-url", 8504, "refusal")]:
    new_tab(f"http://127.0.0.1:{port}/"); wait_for_load()
    cdp("Emulation.setDeviceMetricsOverride", width=1440, height=1300, deviceScaleFactor=1, mobile=False)
    for _ in range(40):
        if marker in js("document.body.innerText"): break
        wait(1)
    wait(4)
    capture_screenshot(f"{out}/{name}.png")
    text = js("document.body.innerText")
    buttons = js("[...document.querySelectorAll('button,a')].map(e=>e.innerText.trim()).filter(Boolean).join(' | ')")
    labels = js("[...document.querySelectorAll('svg text')].map(t=>t.textContent).filter(s=>/\\d{4}-\\d{2}-\\d{2}/.test(s)).join(' | ')")
    print(json.dumps({"view": name, "text": text, "buttons": buttons, "x_labels": labels}))
    cdp("Emulation.clearDeviceMetricsOverride")
PY

# API journeys (J8-J14) through the shared script, then the extra steps.
TOKENS="$(cat "$SCRATCH/tokens-flat.json")"
DEMO_NULL_NODE=00000000-0000-4000-8000-0000000000b2 API=http://127.0.0.1:8765 OUT="$OUT" TOKENS_JSON="$TOKENS" \
  timeout 300 browser-harness < docs/user-journeys/validate_api_journeys.py | grep -v -E 'update available|agents:' >"$SCRATCH/results.jsonl"
mkdir -p "$SCRATCH/fresh"
DEMO_NODE="$(python3 -c 'import uuid;print(uuid.uuid4())')" API=http://127.0.0.1:8765 OUT="$SCRATCH/fresh" TOKENS_JSON="$TOKENS" \
  timeout 300 browser-harness < docs/user-journeys/validate_api_journeys.py | grep -v -E 'update available|agents:' | grep '"J11' | sed 's/"J11-api-trial-ledger"/"J11-fresh-node"/' >>"$SCRATCH/results.jsonl"
cp "$SCRATCH/fresh/J11-api-trial-ledger.png" "$OUT/J11-api-trial-ledger-fresh-node.png"
OUT="$OUT" TOKENS_JSON="$TOKENS" timeout 180 browser-harness <<'PY' | grep -v -E 'update available|agents:' >>"$SCRATCH/results.jsonl"
import os, json
out = os.environ["OUT"]; tok = json.loads(os.environ["TOKENS_JSON"])
new_tab("http://127.0.0.1:8766/healthz"); wait_for_load()
r = json.loads(js("""(async()=>{const r=await fetch('/risk/halt',{method:'POST',headers:{'Authorization':'Bearer %s','Content-Type':'application/json'},body:'{}'});return JSON.stringify({status:r.status,body:await r.text()})})()""" % tok["risk"]))
print(json.dumps({"journey": "J13-no-engine", "call": "halt, no engine", "status": r["status"], "traceback": "Traceback" in r["body"], "body": r["body"][:300]}))
js(f"document.open();document.write({json.dumps('<h1>J13 step 3: halt with no execution engine bound</h1><pre style=white-space:pre-wrap>'+str(r['status'])+' '+r['body'].replace('<','&lt;')+'</pre>')});document.close();")
capture_screenshot(f"{out}/J13-halt-no-engine.png")
cdp("Network.enable"); cdp("Network.setExtraHTTPHeaders", headers={"Authorization": "Bearer " + tok["metrics:read"]})
goto_url("http://127.0.0.1:8765/"); wait_for_load(); wait(1)
print(json.dumps({"journey": "J14-index", "call": "rendered index", "status": 200, "traceback": False, "body": js("document.body.innerText")[:300]}))
capture_screenshot(f"{out}/J14-index-rendered.png", full=True)
cdp("Network.setExtraHTTPHeaders", headers={})
PY
python3 - "$SCRATCH/results.jsonl" <<'PY'
import json, sys
for line in open(sys.argv[1]):
    try: d = json.loads(line)
    except ValueError: continue
    print(d["journey"][:14].ljust(14), str(d["status"]).ljust(4), "TB!" if d.get("traceback") else "   ", d["call"][:40].ljust(40), d["body"][:150].replace("\n", " "))
PY
