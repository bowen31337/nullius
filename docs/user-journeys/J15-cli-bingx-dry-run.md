---
id: J15-cli-bingx-dry-run
title: Dry-run the book onto BingX VST
persona: Operator
source: additions_spec_bingx_dry_run.xml features 1-4 (Stage 0)
status: pass
last_checked: run 7
evidence: screenshots/run-7/J15-step1-dry-run.txt, screenshots/run-7/J15-step2-client-order-ids.txt, screenshots/run-7/J15-step3-rerun.txt, screenshots/run-7/J15-step4-sockets-blocked.txt, screenshots/run-7/J15-step5-missing-book.txt
---

# J15 — Dry-run the book onto BingX VST

The operator mirrors a book onto BingX's VST (demo) perpetual-swap venue
without sending anything: the command prints the orders it would send and
the legs it refuses. Stage 0 has no UI and no network. Its surface is a
shell command, so the evidence is the command's captured output, rendered
in the browser for a screenshot like J13's step 3.

## Preconditions

- Repository checkout with the workspace synced; no credentials, no
  `DATABASE_URL`, no network needed.
- The recorded VST fixtures and the synthetic book under
  `packages/router/tests/fixtures/bingx_vst/` (`contracts.json`,
  `premium_index.json`, `synthetic_book.json`).

## Steps

1. Run `python -m router.bingx_dry_run --book synthetic_book.json
   --contracts contracts.json --marks premium_index.json`.
   Expect: exit `0` and seven JSON lines: five orders and two refusals.
   - BTC-USDT BUY 0.0140 LIMIT PostOnly 83137.3
   - ETH-USDT SELL 0.558 LIMIT PostOnly 2685.87
   - SOL-USDT BUY 8.44 LIMIT PostOnly 118.392
   - DOGE-USDT SELL 5329 MARKET (no price)
   - 1000PEPE-USDT BUY 69446 LIMIT PostOnly 0.0043199
   - AGLD-USDT refused `below_min_notional`
   - NCFXUSD2ARS-USDT refused `not_tradable`
2. Read every order's `clientOrderID`.
   Expect: at most 40 lowercase hex characters, equal to the first 40
   characters of the router's 64-hex identifier for (book_id,
   rebalance_ts, symbol).
3. Run the same command a second time.
   Expect: byte-identical output, so a re-run would place the same
   orders under the same identifiers.
4. Run it with socket creation patched to raise.
   Expect: the same seven lines and exit `0`. No connection is attempted
   and no traceback appears.
5. Run it with `--book` naming a file that does not exist.
   Expect: a non-zero exit with a one-line refusal naming the file, and
   no traceback.

## Result

See [_run-log.md](_run-log.md) for every run's verdict, failing step and evidence.
