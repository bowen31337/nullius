---
id: J14-api-discoverability
title: Discover what the API serves, and get clean errors
persona: Any
source: api_endpoints_summary
status: pass
last_checked: 2026-09-28
evidence: packages/api/tests/test_discoverability.py
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

Implemented and unit-tested in `packages/api/tests/test_discoverability.py` (11 cases, all green):
`GET /` answers a self-contained, theme-aware HTML index listing every declared route with its
verb, component and configured/unconfigured state, HTML-escaped; `GET /healthz` answers a bare
`200`; both are GET-only and answer `405` with an `Allow` header on a wrong verb; the index names
no traceback or filesystem path. Steps 3 and 4 (the token gate, feature 18) are not yet wired —
`/healthz` is already served token-free and the dispatch keys the gate off `path == HEALTHZ_PATH`,
so feature 18 gates `/` and the table routes without touching the probe.

See [_run-log.md](_run-log.md) for every run's verdict, failing step and evidence.
