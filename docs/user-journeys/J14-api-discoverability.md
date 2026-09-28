---
id: J14-api-discoverability
title: Discover what the API serves, and get clean errors
persona: Any
source: api_endpoints_summary
status: untested
last_checked: —
evidence: —
---

# J14 — Discover what the API serves, and get clean errors

## Preconditions

- API running on the demo store.

## Steps

1. Open `/` with a token.
   Expect: An HTML index of every route, its verb and whether its component is configured.
2. Open `/healthz` without a token.
   Expect: `200`.
3. Open an unknown path; send GET to a POST-only route.
   Expect: `404` JSON; `405` with an `Allow` header.
4. Call any route with no token, an unknown token, an out-of-scope token.
   Expect: `401`, `401`, `403`; no body ever carries a traceback or path.

## Result

See [_run-log.md](_run-log.md) for every run's verdict, failing step and evidence.
