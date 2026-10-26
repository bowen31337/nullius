# Pre-registration: paper-only forward shadow of a de-correlated multi-theme book (shadow v2)

- **Registered:** 2026-10-26 02:14:52 UTC, before the shadow's first book exists. `main` is at `0b46318b` (`aeb699e1` the shadow construction feature: the forward shadow honours the config's book weighting, caps per-name weight and can scale nodes to equal risk; default path byte-identical, the v1 and paper-attention books reproduced byte-for-byte after the merge).
- **Why this test.** Four archive series (`2026-10-19-m2-wide-h5` VOID, `2026-10-20-m2-wide-h5-v2` FAIL t 1.23, `2026-10-21-m2-short-h5` FAIL t −0.84, `2026-10-22-m2-h10-lowvol` FAIL t −0.57) established that the engine finds repeatable cross-sectional rankings (out-of-sample rank-IC t 2 to 5 on committed picks) and that no single-theme dollar-neutral book built on them clears t 2 on the archive window, because every such book is a concentrated bet on one idea whose return is decided by a few squeeze dates. The archive out-of-sample window has been read thirteen times and can no longer validate a construction choice for these signals. This registration therefore tests the project's own thesis, a de-correlated book of several weak signals, on data none of them has seen: the forward market from the day the first book is built. It is paper-only; nothing trades.
- **What this is not:** no capital, no VST account, no dreaming. Not a new archive series. A pass earns a VST shadow of the same book, pre-registered then; a fail closes the multi-theme book on these inputs.

## The book
- **Nodes (fixed now, by rule, no out-of-sample figure consulted in the rule):** for each theme with at least one *real* committed `m2-fixed` pick in the four series above, the real pick with the highest in-sample `ir_tstat` under its own series' construction; at most one node per theme; planted-null picks excluded (`1e00d94c`, `f3896a87`). That rule yields four nodes:

  | Theme | Node | Series / campaign | Depth | IS IC t | IS IR t | Turnover |
  |---|---|---|---|---|---|---|
  | funding-crowding | `f9d5fba9-dbde-52d7-a061-086b0afc63ce` | short-h5 `caa328f0` | 1 | 2.12 | 4.64 | 0.23 |
  | low-volatility | `e718c720-4489-5e49-8a11-93841cd2d6a7` | h10-lowvol `015bccd0` | 2 | 6.66 | 3.82 | 0.17 |
  | intermediate-momentum | `886a711a-…` (full id in the nodes file) | wide-h5 v1 `870d4594` | 1 | 1.58 | 2.81 | 0.29 |
  | basis-premium | `c526fc4b-7d6a-5201-b96d-dcc50990e290` | wide-h5 v2 `216ee364` | 1 | 2.28 | 2.08 | 0.35 |

  Disclosure: the operator has read every one of these nodes' archive out-of-sample figures (the series RESULTs). The rule above was fixed before this document was written and does not use them; a different rule (for example, the pick with the best out-of-sample reading per theme) would have been a selection on the burnt window and is not used.
- **Construction:** each node's daily book from the evaluation config `evaluation-config-wide-h5-maker-iv-mh.json` (perp, maker, beta-neutral to BTC over 60 days, **`inverse_vol` weighting**, vol window 60 days) through the shadow's `shadow-book`; nodes combined with `--node-weighting inverse_vol` (each node's weight vector scaled by the inverse of its trailing 60-day realised book volatility, then averaged); the combined book capped at `--max-name-weight 0.04` with renormalisation to `--gross 1.0`; equity 10 000 USDT notional for reporting. Inverse-vol was chosen because it was the lowest-variance construction in every series (per-period sd 32 to 78 bp against 140 to 460 for the tail books) and the only one never dominated by a single date; the cap bounds the squeeze exposure the RESULTs documented. Both are execution choices named here, not fitted.
- **Cadence:** a new book every 7 days on the Monday grid anchored 2022-01-03 (`--grid-days 7`), built by the daily 09:50 UTC paper run from the day's sealed shadow snapshot, held between decision dates exactly as the paper attention shadow is.
- **Service** (committed as `0b46318b`): `nullius-shadow-v2.service` and timer (a copy of the paper unit with `SHADOW_NODES_PAPER` naming `~/.config/nullius/shadow/nodes-v2.txt`, `SHADOW_OUT_PAPER` naming `~/.local/share/nullius/shadow-v2/book.json`, and `ENV_CAMPAIGN_TPL` naming a template whose `NULLIUS_EVALUATION_CONFIG` is the inverse-vol config); history under `~/.local/share/nullius/shadow-v2/history/`. The two live shadows and their units are untouched.

## Dry build before registration
The book was built once into the scratchpad from the 2026-10-25 snapshot with the registered flags (2026-10-26 02:13 UTC): `book_id shadow-2026-10-19-4e3427ae935d`, 70 names (37 long, 33 short), gross 1.0, max |w| 0.0145 (the 0.04 cap did not bind), node_weighting inverse_vol, construction inverse_vol, book_beta 4e-17. That file is not the shadow's first book; the first book is the one the service writes at 09:55 UTC today, and the window starts the next day.

## Primary outcome (decided now)
`./run.sh shadow-eval --history ~/.local/share/nullius/shadow-v2/history --grid-days 7 --first-decision 2026-10-19 --window-start 2026-10-27T00:00Z --window-end 2027-01-25T00:00Z` with no `--vst-db` (and `DATABASE_URL` unset so validity reads `unchecked`): the paper book's cumulative net return over the 90-day window at `--cost-bps 5` is **> 0 and `ir_t` (mean/sd·√n over scored days) ≥ 1.0**: pass; otherwise fail. The window is the 90 days from the first in-force date; a day without a sealed snapshot is a lost day recorded in an addendum and extends the window. One computation at the window's end; interim readings are reported daily and decide nothing.

## Secondary (reported, not decisive)
- Per-node paper returns over the same days (each node's own inverse-vol book, built by the same command with one `--node`), their pairwise correlations and the realised N_eff of the four.
- The uncapped book (`--max-name-weight` absent) and the equal-node-weight book, same days.
- Realised beta, funding share, turnover, max drawdown, the number of capped names per decision date.
- The same four nodes' archive out-of-sample portfolio under the inverse-vol config, reported as context only (those figures have been read).

## What follows
- **Pass:** a VST shadow of the same book under the same construction, pre-registered before it trades, with the margin headroom question settled in that registration.
- **Fail:** the multi-theme inverse-vol book on these four inputs is recorded as not paying forward; the signals stay as research findings. What comes after is new inputs or the dreaming-selected commit rule's picks (M3b), each pre-registered.

## Disclosures
- The operator has read the archive out-of-sample figures of all four nodes and of every other candidate. The node rule, the construction and the cap were chosen knowing the series RESULTs' qualitative findings (squeeze concentration; inverse-vol's lower variance), which were derived from the burnt window. That is why this test is forward-only and why its pass earns another forward test rather than capital.
- Shadow v1's VST leg is in an invalid stretch (its Addenda 9 and 10); the execution fix (`7ac5f1e3 and the follow-up spec d42b75e0`) is declared in its Addendum 11 and is unrelated to this registration.
- Cost: none beyond the daily paper run's compute.
