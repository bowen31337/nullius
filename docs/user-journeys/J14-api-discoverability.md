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

- `python -m nullius_api` running against the demo store, with
  `NULLIUS_API_TOKENS_FILE` naming a token file that holds at least a
  `metrics:read` and a `risk` token (feature 18).

## Steps

1. Open `/` with a `metrics:read` token.
   Expect: An HTML index of every route, its verb and whether its component is configured.
2. Open `/healthz` without a token.
   Expect: `200`. It is the one route that answers without one.
3. Open an unknown path; send GET to a POST-only route.
   Expect: `404` JSON; `405` with an `Allow` header. Both with a token —
   without one, every path including an unknown one answers `401`, so that
   an unauthenticated caller cannot map the surface.
4. Call any route with no token, an unknown token, an out-of-scope token.
   Expect: `401`, `401`, `403`; no body ever carries a traceback or path.
   The `403` names the route, the scope it wants and the scope presented;
   neither refusal repeats the token.

## Result

See [_run-log.md](_run-log.md) for every run's verdict, failing step and evidence.
