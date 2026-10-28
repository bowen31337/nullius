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

## Addendum 3 — 2026-10-28 07:40 UTC: the two books in force are equal-weight, not the registered inverse-vol book (cap defect found; fix queued)

**Finding.** While dry-building the shadow v3 book (the same construction on 30 names) every name came out at exactly 1/30, and re-reading the two v2 books showed the same shape: `shadow-2026-10-19-4e3427ae935d` and `shadow-2026-10-26-4e3427ae935d` carry 68 of 70 names at exactly |w| 0.014612 and two names near zero. The per-node books under the same config are genuine inverse-vol books (30 distinct magnitudes from 0.0014 to 0.12 on the 30-name universe), so the equalisation happens in the combine.

**Mechanism** (`orchestrator.shadow._cap_name_weights`, added by `aeb699e1` for this registration). The cap clips each |w| to `--max-name-weight` *before* the book is normalised to `--gross`, then rescales. Under `--node-weighting inverse_vol` each node's vector is divided by its own trailing book sigma (about 0.01), so the mean of the four vectors arrives with a gross near 50 to 100: every name exceeds 0.04 on the first pass, all are clipped to 0.04, and the rescale to gross 1.0 lands every clipped name at the same 1/68.4. `n_capped` reads 0 because 0.0146 is not 0.04, so nothing in the JSON line flagged it. Reproduced in a shell by feeding `_cap_name_weights` the same mean vector at gross 1, 2 and 100: the first two give 28 distinct magnitudes with 3 names at the cap, the third gives 2 magnitudes and `n_capped` 0. The uncapped path (`_combine`) is unaffected; the registration's dry build matched the service's first book byte for byte because the defect is deterministic, which proved reproducibility and nothing about the construction.

**What has actually been held.** From 2026-10-27 (the window's first scored day) the paper book in force is the equal-weight sign book of the inverse-vol-scaled consensus: long 1/68.4 in every name the four nodes' scaled mean is positive on, short 1/68.4 where negative, two names with near-cancelling node views at small weight. It is dollar-near-neutral and the per-node beta neutrality is preserved only in the mean sense the JSON line reports. This is a different construction from the registered "inverse-vol weighting, capped at 0.04", and the 0.04 cap never did anything.

**Decision.** The registration is not changed and the window is not restarted. The two books in force stay as held (the daily run's hold rule keeps them; replacing a book mid-grid would be an intervention the registration does not allow). The defect is being fixed through claw-forge today (cap applied after normalising to gross, then clip and rescale iteratively, as the spec always meant a cap on a *fraction of gross* to work); from the fix the daily run builds the registered construction, so the book for the next decision date (2026-11-02, in force from 2026-11-04 nominal) is expected to be the first genuine inverse-vol capped book. The primary outcome is computed as registered over whatever the history holds; this addendum declares that its first eight days were held under the equal-weight artefact. As a secondary, the registered construction's book for 2026-10-19 and 2026-10-26 will be rebuilt under the fixed code into the scratchpad and its paper return over the same days reported beside the held book's, so the cost of the artefact is measured rather than guessed. Shadow v3's registration follows the fix and is built correctly from its first book; its paired comparison with v2 over 2026-10-29 → 2026-11-03 therefore compares an inverse-vol book with an equal-weight one, and says so.

**Disclosure.** The v3 dry-build weights and the two v2 books' weights were read for this analysis. No forward return had been read: the first v2 scored day is produced by today's 09:55 UTC run, after this addendum.
