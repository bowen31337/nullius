#!/usr/bin/env bash
# Paper-only forward shadow: rebuild a second research book from the shadow
# lake's newest snapshot, for scoring with `run.sh shadow-eval` only.
#
# Runs AFTER deploy/shadow/shadow_daily.sh (which refreshes the lake, seals the
# snapshot and fetches the BingX documents). It reuses all of that and adds one
# thing: a book from a second node list, written to its own directory with its
# own history. It never touches the VST bot's active_book.json, never calls
# shadow_switch.sh, and places no order anywhere. The v1 shadow
# (docs/preregistration/2026-10-15-shadow-v1.md) is unaffected.
#
# Pre-registration: docs/preregistration/2026-10-19-shadow-paper-attention.md
#
# Environment (all optional):
#   SHADOW_LAKE         the shadow lake root (default ~/.local/share/nullius/lake-shadow)
#   SHADOW_NODES_PAPER  CAMPAIGN_ID/NODE_ID per line (default ~/.config/nullius/shadow/nodes-paper.txt)
#   SHADOW_OUT_PAPER    the book path (default ~/.local/share/nullius/shadow-paper/book.json)
#   SHADOW_METRICS      1 to require the metrics stream on the decision date (as the daily run does)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
RUN_SH="${REPO_ROOT}/run.sh"
SHADOW_LAKE="${SHADOW_LAKE:-$HOME/.local/share/nullius/lake-shadow}"
SHADOW_NODES_PAPER="${SHADOW_NODES_PAPER:-$HOME/.config/nullius/shadow/nodes-paper.txt}"
SHADOW_OUT_PAPER="${SHADOW_OUT_PAPER:-$HOME/.local/share/nullius/shadow-paper/book.json}"
SHADOW_METRICS="${SHADOW_METRICS:-0}"
# Extra shadow-book flags, word-split (shadow v2: "--grid-days 7 --max-name-weight 0.04 --node-weighting inverse_vol").
SHADOW_BOOK_EXTRA_ARGS="${SHADOW_BOOK_EXTRA_ARGS:-}"
# A perp book must be priced on the USD-M schedule; shadow-book refuses the
# shipped spot default, so default it here rather than depend on the unit alone.
export NULLIUS_COST_MODEL_PATH="${NULLIUS_COST_MODEL_PATH:-${REPO_ROOT}/packages/cost-model/src/cost_model/binance_usdm.yaml}"

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }

[[ -f "${SHADOW_NODES_PAPER}" ]] || { echo "error: ${SHADOW_NODES_PAPER} not found; one CAMPAIGN_ID/NODE_ID per line" >&2; exit 1; }
CONTRACTS_PATH="${SHADOW_LAKE}/contracts.json"
TICKER_PATH="${SHADOW_LAKE}/ticker.json"
[[ -f "${CONTRACTS_PATH}" && -f "${TICKER_PATH}" ]] || { echo "error: ${CONTRACTS_PATH} or ${TICKER_PATH} missing; run shadow_daily.sh first" >&2; exit 1; }

# The newest sealed snapshot: the daily run names them by UTC seal time, so the
# lexically last directory is the one it just built.
SNAPSHOT_PATH="$(find "${SHADOW_LAKE}/snapshots" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort | tail -n1)"
[[ -n "${SNAPSHOT_PATH}" ]] || { echo "error: no snapshot under ${SHADOW_LAKE}/snapshots" >&2; exit 1; }
SNAPSHOT_PATH="${SHADOW_LAKE}/snapshots/${SNAPSHOT_PATH}"

NODE_ARGS=()
if [[ "${SHADOW_METRICS}" == "1" ]]; then
  NODE_ARGS+=(--require-stream metrics)
fi
while IFS= read -r line || [[ -n "${line}" ]]; do
  line="${line%$'\r'}"
  [[ -z "${line}" ]] && continue
  [[ "${line}" == \#* ]] && continue
  NODE_ARGS+=(--node "${line}")
done < "${SHADOW_NODES_PAPER}"
[[ "${#NODE_ARGS[@]}" -gt 0 ]] || { echo "error: ${SHADOW_NODES_PAPER} has no CAMPAIGN_ID/NODE_ID lines" >&2; exit 1; }

mkdir -p "$(dirname "${SHADOW_OUT_PAPER}")"
log "paper shadow-book --snapshot ${SNAPSHOT_PATH} --out ${SHADOW_OUT_PAPER}"
BOOK_LINE="$("${RUN_SH}" shadow-book \
  --snapshot "${SNAPSHOT_PATH}" \
  --out "${SHADOW_OUT_PAPER}" \
  --contracts "${CONTRACTS_PATH}" \
  --ticker "${TICKER_PATH}" \
  ${SHADOW_BOOK_EXTRA_ARGS} \
  "${NODE_ARGS[@]}")"
echo "${BOOK_LINE}"

# Keep every book as written, the same convention as the v1 history, so
# `run.sh shadow-eval --history <this dir>` can rebuild exactly what was held.
HISTORY_DIR="$(dirname "${SHADOW_OUT_PAPER}")/history"
mkdir -p "${HISTORY_DIR}"
BOOK_ID="$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["book_id"])' "${SHADOW_OUT_PAPER}")"
if [[ ! -f "${HISTORY_DIR}/${BOOK_ID}.json" ]]; then
  cp -- "${SHADOW_OUT_PAPER}" "${HISTORY_DIR}/${BOOK_ID}.json"
fi
printf '%s\n' "${BOOK_LINE}" >> "${HISTORY_DIR}/shadow-book.jsonl"
log "done"
