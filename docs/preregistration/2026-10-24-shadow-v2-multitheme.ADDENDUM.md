# Addenda to `2026-10-24-shadow-v2-multitheme.md`

The registration is immutable (`.sha256` beside it). This file records what happened after it, dated, newest last. Nothing here changes the construction, the window, the criteria or the inputs.

## Addendum 1 — 2026-10-26 10:35 UTC: the first book, written on the second attempt of the day

**The scheduled 09:55 UTC run failed before building anything** (`Result exit-code`, status 2, one second). Cause: the unit's `Environment=SHADOW_BOOK_EXTRA_ARGS=--grid-days 7 --max-name-weight 0.04 --node-weighting inverse_vol` line was unquoted, so systemd split it on spaces, kept `SHADOW_BOOK_EXTRA_ARGS=--grid-days` and logged the other four words as "Invalid environment assignment, ignoring". The wrapper then passed a bare `--grid-days` and `orchestrator.shadow` exited with "argument --grid-days: expected one argument". The `OnFailure` alert fired (Telegram, 09:55:04 UTC). The registration's dry build at 02:13 UTC had been run from a shell with the flags quoted, which is why it did not catch this.

**Fix:** the value was wrapped as `Environment="SHADOW_BOOK_EXTRA_ARGS=…"` (the installed unit is a symlink to `deploy/systemd/nullius-shadow-v2.service`), `daemon-reload` showed the full value, and the service was started once by hand at 10:25 UTC. No other change; the flags, nodes file, template, output path and timer are as registered.

**First book (10:25:03 → 10:25:51 UTC, exit 0),** from the same sealed snapshot the 09:55 run would have used (`2026-10-26T09:32:07Z_50f3fa`, decision grid anchored 2022-01-03 at 7 days):

| Field | Value |
|---|---|
| `book_id` | `shadow-2026-10-19-4e3427ae935d` (identical to the registration's dry build) |
| `as_of` / `decision_date` | 2026-10-19 / 2026-10-19, `held false` |
| nodes | 4 (`f9d5fba9…`, `e718c720…`, `886a711a…`, `c526fc4b…`), `node_weighting inverse_vol` |
| names | 70 (37 long, 33 short); 30 dropped for having no BingX contract, 0 for price mismatch |
| gross / beta | 1.0 / 3.8e-17 |
| `max_name_weight` / `n_capped` | 0.04 / 0, largest |w| 0.0145 |

The book id matching the dry build means the construction is reproducible from the sealed snapshot and the registered flags; the 10-hour delay changed nothing because both runs read the same snapshot. The window still opens 2026-10-27 00:00 UTC; this book is the one in force on the first scored day, and the next decision date is 2026-11-02.

**Disclosure.** The book's weights were read (the jsonl line and the history file), as the registration's dry build already was. No forward return exists yet to read.

## Addendum 2 — 2026-10-27 10:05 UTC: the first timer run under the quoted unit, and the second book on the grid

**Timer run (nullius-shadow-v2.service, 09:55 UTC):** Result success, exit 0, from the day's sealed snapshot `2026-10-27T09:32:06Z_b9ee6c`. The quoted `SHADOW_BOOK_EXTRA_ARGS` line reached the wrapper intact (`max_name_weight 0.04`, `node_weighting inverse_vol` in the book line); the 2026-10-26 defect of Addendum 1 is confirmed fixed on the timer, not only by hand.

**Second book, as the 7-day Monday grid dictates:** `shadow-2026-10-26-4e3427ae935d`, `decision_date 2026-10-26, held false`, the same four nodes, 70 names (40 long, 30 short; 30 dropped for having no BingX contract), gross 1.0, beta −2.4e-17, `n_capped 0`, largest |w| 0.0146. Against the 2026-10-19 book: the same 70 names, 61 on the same side and 9 flipped, one-way turnover 0.128. In force from 2026-10-28 (the nominal rule, decision date plus two days); the 2026-10-19 book covers the window's first day, 2026-10-27.

**Registered evaluation command** (`shadow-eval --history … --grid-days 7 --first-decision 2026-10-19 --window-start 2026-10-27T00:00Z --window-end 2027-01-25T00:00Z`, no `--vst-db`, `DATABASE_URL` unset): `n_days 0`, two books listed with `in_force_rule nominal`, `validity unchecked` (paper-only, as registered). The lake runs through 2026-10-26, so the window's first scored day appears at tomorrow's run.

**Disclosure.** The new book's weights were read for the comparison above; no forward return exists yet.
