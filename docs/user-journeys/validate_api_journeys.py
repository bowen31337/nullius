# ruff: noqa: F821  (new_tab, js, capture_screenshot, ... are injected by browser-harness)
"""Browser validation of the HTTP API journeys (J8-J14).

Run inside browser-harness (helpers such as new_tab, js and
capture_screenshot are pre-imported):

    API=http://127.0.0.1:8765 TOKENS_JSON='{"metrics:read": "...", ...}' \
    OUT=docs/user-journeys/screenshots/run-2 \
    BU_CDP_URL=http://localhost:9222 browser-harness < docs/user-journeys/validate_api_journeys.py

A browser cannot POST from the address bar, so each journey opens the API's
own origin and drives its calls with fetch() from that page (same origin, so
no CORS is involved). The requests and responses are written into the page
as a report and screenshotted, one screenshot per journey. A summary of every
call (journey, request, status) is printed as JSON lines for _run-log.md.
"""

import json
import os

API = os.environ.get("API", "http://127.0.0.1:8765")
OUT = os.environ.get("OUT", "docs/user-journeys/screenshots/run-2")
TOKENS = json.loads(os.environ.get("TOKENS_JSON", "{}"))
NODE = os.environ.get("DEMO_NODE", "00000000-0000-4000-8000-0000000000a1")
EPOCH = os.environ.get("DEMO_EPOCH", "epoch-demo-2026-03")
UNKNOWN = "ffffffff-0000-4000-8000-000000000000"
HEX = "a" * 64

CRITERIA = {
    "theta": 0.3,
    "alpha": 0.05,
    "max_fdr_deploy": 0.25,
    "min_worlds": 50,
    "min_coverage_strata": 3,
    "min_forward_days": 90,
}


def call(method, path, body=None, scope=None, token=None, raw=None):
    """One fetch() from the API's origin; returns status, headers and body."""
    headers = {}
    if token is None and scope is not None:
        token = TOKENS.get(scope)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if raw is not None:
        payload = raw
    elif body is not None:
        payload = json.dumps(body)
    else:
        payload = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
    script = f"""
    (async () => {{
      const r = await fetch({json.dumps(path)}, {{method: {json.dumps(method)},
        headers: {json.dumps(headers)}, body: {json.dumps(payload)} }});
      const text = await r.text();
      const h = {{}}; r.headers.forEach((v, k) => h[k] = v);
      return JSON.stringify({{status: r.status, headers: h, body: text}});
    }})()
    """
    return json.loads(js(script))


def report(journey, title, calls):
    """Render the calls into the page, screenshot it, print one line per call."""
    rows = []
    for label, req, res in calls:
        try:
            pretty = json.dumps(json.loads(res["body"]), indent=2)
        except ValueError:
            pretty = res["body"]
        rows.append(
            f"<section><h3>{label}</h3><p><code>{req}</code> &rarr; "
            f"<b class='s{res['status'] // 100}'>{res['status']}</b></p>"
            f"<pre>{pretty[:1800].replace('<', '&lt;')}</pre></section>"
        )
        print(
            json.dumps(
                {
                    "journey": journey,
                    "call": label,
                    "request": req,
                    "status": res["status"],
                    "allow": res["headers"].get("allow"),
                    "traceback": "Traceback" in res["body"],
                    "body": res["body"][:400],
                }
            )
        )
    html = (
        "<style>body{font:14px system-ui;margin:24px;max-width:1100px}"
        "pre{background:#f4f4f4;padding:8px;white-space:pre-wrap;font-size:12px}"
        ".s2{color:#070}.s4{color:#a60}.s5{color:#b00}h3{margin:12px 0 4px}</style>"
        f"<h1>{journey} — {title}</h1><p>{API}</p>" + "".join(rows)
    )
    js(f"document.open(); document.write({json.dumps(html)}); document.close();")
    capture_screenshot(f"{OUT}/{journey}.png", full=True)


new_tab(API + "/healthz")
wait_for_load()

calls = []
for label, method, path, scope, token in [
    ("index", "GET", "/", "metrics:read", None),
    ("health, no token", "GET", "/healthz", None, None),
    ("unknown path", "GET", "/no-such-route", "metrics:read", None),
    ("wrong verb", "GET", "/risk/halt", "risk", None),
    ("no token", "GET", "/metrics/fdr-deploy", None, None),
    ("unknown token", "GET", "/metrics/fdr-deploy", None, "not-a-real-token"),
    ("out-of-scope token", "POST", "/risk/halt", "metrics:read", None),
]:
    calls.append((label, f"{method} {path}", call(method, path, scope=scope, token=token)))
report("J14-api-discoverability", "Discover what the API serves, and get clean errors", calls)

report(
    "J08-api-metrics",
    "Read the three observability metrics over HTTP",
    [
        (p, f"GET {p}", call("GET", p, scope="metrics:read"))
        for p in ("/metrics/fdr-deploy", "/metrics/instrument-status", "/metrics/regime-coverage")
    ]
    + [("fdr-deploy, no token", "GET /metrics/fdr-deploy", call("GET", "/metrics/fdr-deploy"))],
)

reg = {"node_id": NODE, "epoch_id": EPOCH, "criteria": CRITERIA}
other = dict(reg, criteria=dict(CRITERIA, theta=0.4))
path = "/promotion/pre-register"
report(
    "J09-api-pre-register",
    "Pre-register promotion criteria",
    [
        ("register the seeded node", f"POST {path}", call("POST", path, reg, "research")),
        ("identical retry", f"POST {path}", call("POST", path, reg, "research")),
        ("different criteria", f"POST {path}", call("POST", path, other, "research")),
        ("unknown node", f"POST {path}", call("POST", path, dict(reg, node_id=UNKNOWN), "research")),
        ("malformed body", f"POST {path}", call("POST", path, raw="{not json", scope="research")),
    ],
)

report(
    "J10-api-forward-test",
    "Promote to forward test and read the decay curve",
    [
        ("promote the seeded node", "POST /forward/promote",
         call("POST", "/forward/promote", {"node_id": NODE, "forward_days": 90}, "research")),
        ("decay curve", f"GET /forward/decay?node_id={NODE}",
         call("GET", f"/forward/decay?node_id={NODE}", scope="research")),
        ("decay, unknown node", "GET /forward/decay?node_id=<unknown>",
         call("GET", f"/forward/decay?node_id={UNKNOWN}", scope="research")),
    ],
)

charge = {
    "node_id": NODE,
    "campaign_id": "00000000-0000-4000-8000-000000000003",
    "outcome": "ok",
    "charges_budget": True,
    "charge_units": 1.0,
    "epoch_id": EPOCH,
    "evaluator_hash": HEX,
    "snapshot_hash": HEX,
    "cost_model_hash": HEX,
    "ts": "2026-03-05T00:00:00+00:00",
}
report(
    "J11-api-trial-ledger",
    "Debit the trial ledger and read K-effective",
    [
        ("debit", "POST /ledger/debit", call("POST", "/ledger/debit", charge, "evaluator")),
        ("identical retry", "POST /ledger/debit", call("POST", "/ledger/debit", charge, "evaluator")),
        ("invalid outcome", "POST /ledger/debit",
         call("POST", "/ledger/debit", dict(charge, outcome="maybe"), "evaluator")),
        ("k-effective", "GET /ledger/k-effective", call("GET", "/ledger/k-effective", scope="evaluator")),
    ],
)

ask = {
    "node_id": NODE,
    "campaign_id": "00000000-0000-4000-8000-000000000003",
    "depth": 1,
    "horizon": 5,
    "symbols": ["BTCUSDT"],
    "date_range": ["2026-01-01", "2026-01-31"],
}
j12 = [
    ("target, seeded node", "POST /target", call("POST", "/target", ask, "evaluator")),
    ("target, unknown node", "POST /target",
     call("POST", "/target", dict(ask, node_id=UNKNOWN), "evaluator")),
]
NULL_NODE = os.environ.get("DEMO_NULL_NODE")
if NULL_NODE:
    # The barrier: the seeded null node must be refused exactly as the real
    # one is, apart from the node id the caller itself sent.
    real = j12[0][2]
    null = call("POST", "/target", dict(ask, node_id=NULL_NODE), "evaluator")
    j12.append(("target, seeded NULL node", "POST /target", null))
    same = (
        null["status"] == real["status"]
        and {k: v for k, v in null["headers"].items() if k != "date"}
        == {k: v for k, v in real["headers"].items() if k != "date"}
        and null["body"].replace(NULL_NODE, "<node>") == real["body"].replace(NODE, "<node>")
    )
    verdict = {"status": 200 if same else 500, "headers": {}, "body": json.dumps(
        {"null_vs_real_identical_apart_from_the_node_id": same})}
    j12.append(("barrier check (computed, not a request)", "null vs real", verdict))
report("J12-api-null-oracle-target", "Ask the null oracle for a target series", j12)

report(
    "J13-api-risk-halt",
    "Trigger the emergency halt",
    [
        ("halt", "POST /risk/halt", call("POST", "/risk/halt", {}, "risk")),
        ("halt again", "POST /risk/halt", call("POST", "/risk/halt", {}, "risk")),
    ],
)
