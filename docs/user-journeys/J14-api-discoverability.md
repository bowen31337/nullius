# J14 — Discover what the API serves, and get clean errors

**Actor:** Any  
**Goal:** Open the API root in a browser and see what is served and what is configured; get structured errors, never a stack trace.  
**Source:** `<api_endpoints_summary>`

## Preconditions

- The API server is running.

## Steps

1. Open `/`.
2. Open `/healthz`.
3. Open an unknown path.
4. Send `GET` to a `POST`-only route.

## Expected result

- `/` lists every route with its verb and whether its component is configured.
- `/healthz` answers `200`.
- Unknown path: `404` JSON. Wrong verb: `405` with an `Allow` header.
- No error body ever contains a traceback or a filesystem path; the server binds `127.0.0.1` unless told otherwise.

## Validation

Browser: open each, read the body, screenshot.

Results and screenshots: see [RESULTS.md](RESULTS.md).
