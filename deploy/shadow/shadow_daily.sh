#!/usr/bin/env bash
# shadow_daily.sh — the forward shadow's daily lake refresh + book rebuild.
#
# additions_spec_forward_shadow.xml, "Forward Shadow" category, feature 4:
# rebuilds the book the VST bot trades from fresh data, with no manual steps.
# Run directly, or through `./run.sh shadow-daily [args]`; nullius-shadow.timer
# (deploy/systemd/) fires it once a day. Nothing in this repository installs
# or enables that timer.
#
# Steps, each logging one line, in order:
#   1. decide the backfill window (an empty lake needs --bootstrap DAYS)
#   2. lake-backfill (bars), then lake-derivs-backfill --source rest for
#      funding and futbars (staged through yesterday), plus, when
#      SHADOW_METRICS=1, a second lake-derivs-backfill --streams metrics on
#      the archive source (metrics has no REST source), over that window
#   3. lake-seal
#   4. prune every snapshot but the newest SHADOW_KEEP
#   5. fetch the public BingX contracts document (no key)
#   6. run.sh shadow-book, one --node per SHADOW_NODES line
#
# The script exits with the first failing step's code. An incomplete or
# unpublished day is not a failure (the backfills exit 0 on it, and the book
# step picks the latest complete date on its own), so every non-zero exit
# stops the run.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
RUN_SH="${REPO_ROOT}/run.sh"

SHADOW_LAKE="${SHADOW_LAKE:-$HOME/.local/share/nullius/lake-shadow}"
SHADOW_NODES="${SHADOW_NODES:-$HOME/.config/nullius/shadow/nodes.txt}"
SHADOW_OUT="${SHADOW_OUT:-$HOME/.local/share/nullius/shadow/book.json}"
SHADOW_KEEP="${SHADOW_KEEP:-3}"
SHADOW_METRICS="${SHADOW_METRICS:-0}"

BOOTSTRAP_DAYS=""

usage() {
  cat <<USAGE
usage: ${BASH_SOURCE[0]} [--bootstrap DAYS] [--help]

Refreshes the forward-shadow lake, seals it, prunes old snapshots, fetches
the BingX contracts document and rebuilds the VST book from the research
nodes named in SHADOW_NODES.

  --bootstrap DAYS   on an empty lake only: stage the last DAYS days of bars
                     (--source rest --top 100) before anything else runs

Variables (current value, from the environment or the default):
  SHADOW_LAKE     = ${SHADOW_LAKE}
  SHADOW_NODES    = ${SHADOW_NODES}
  SHADOW_OUT      = ${SHADOW_OUT}
  SHADOW_KEEP     = ${SHADOW_KEEP}
  SHADOW_METRICS  = ${SHADOW_METRICS}
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --bootstrap)
      if [[ $# -lt 2 ]]; then
        echo "error: --bootstrap needs a DAYS argument" >&2
        exit 1
      fi
      BOOTSTRAP_DAYS="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "error: unknown argument '$1'" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ -n "${BOOTSTRAP_DAYS}" ]] && ! [[ "${BOOTSTRAP_DAYS}" =~ ^[0-9]+$ && "${BOOTSTRAP_DAYS}" -gt 0 ]]; then
  echo "error: --bootstrap DAYS must be a positive integer, got '${BOOTSTRAP_DAYS}'" >&2
  exit 1
fi

log() {
  printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1"
}

if [[ ! -f "${SHADOW_NODES}" ]]; then
  echo "error: ${SHADOW_NODES} not found; one CAMPAIGN_ID/NODE_ID per line" >&2
  exit 1
fi

mkdir -p "${SHADOW_LAKE}"
mkdir -p "$(dirname "${SHADOW_OUT}")"

UNIVERSE_JSON="${SHADOW_LAKE}/universe.json"
STAGED_BARS_DIR="${SHADOW_LAKE}/staging/bars"
YESTERDAY="$(date -u -d 'yesterday' +%Y-%m-%d)"

# -- step 1: decide the backfill window ----------------------------------------

lake_is_empty() {
  [[ ! -d "${STAGED_BARS_DIR}" ]] || [[ -z "$(ls -A "${STAGED_BARS_DIR}" 2>/dev/null)" ]]
}

if lake_is_empty; then
  if [[ -z "${BOOTSTRAP_DAYS}" ]]; then
    echo "error: ${SHADOW_LAKE} has no staged bars; pass --bootstrap DAYS to stage an initial universe" >&2
    exit 1
  fi
  FIRST="$(date -u -d "${YESTERDAY} -$((BOOTSTRAP_DAYS - 1)) days" +%Y-%m-%d)"
  LAST="${YESTERDAY}"
  BARS_SOURCE_ARGS=(--source rest --top 100)
  log "step 1/6: empty lake, bootstrapping ${BOOTSTRAP_DAYS} days (${FIRST}..${LAST}, --top 100)"
else
  if [[ ! -f "${UNIVERSE_JSON}" ]]; then
    echo "error: ${UNIVERSE_JSON} is missing but ${STAGED_BARS_DIR} is not empty" >&2
    exit 1
  fi
  FIRST_SYMBOL="$(python3 -I -c '
import json, sys
with open(sys.argv[1], encoding="utf-8") as fh:
    data = json.load(fh)
print(data["symbols"][0])
' "${UNIVERSE_JSON}")"
  LATEST_DATE="$(find "${STAGED_BARS_DIR}/symbol=${FIRST_SYMBOL}" -mindepth 1 -maxdepth 1 -type d -name 'date=*' -printf '%f\n' 2>/dev/null | sed 's/^date=//' | sort | tail -n1)"
  if [[ -z "${LATEST_DATE}" ]]; then
    echo "error: no staged bars for ${FIRST_SYMBOL} under ${STAGED_BARS_DIR}" >&2
    exit 1
  fi
  FIRST="$(date -u -d "${LATEST_DATE} +1 day" +%Y-%m-%d)"
  LAST="${YESTERDAY}"
  SYMBOLS="$(python3 -I -c '
import json, sys
with open(sys.argv[1], encoding="utf-8") as fh:
    data = json.load(fh)
print(",".join(data["symbols"]))
' "${UNIVERSE_JSON}")"
  BARS_SOURCE_ARGS=(--source rest --symbols "${SYMBOLS}")
  log "step 1/6: incremental window ${FIRST}..${LAST}, universe from ${UNIVERSE_JSON}"
fi

# -- step 2: lake-backfill, lake-derivs-backfill --------------------------------

if [[ "${FIRST}" > "${LAST}" ]]; then
  log "step 2/6: bars already staged through ${LAST}"
else
  log "step 2/6: lake-backfill over ${FIRST}..${LAST}"
  LAKE="${SHADOW_LAKE}" "${RUN_SH}" lake-backfill --first "${FIRST}" --last "${LAST}" "${BARS_SOURCE_ARGS[@]}"
fi

if [[ ! -f "${UNIVERSE_JSON}" ]]; then
  echo "${UNIVERSE_JSON} absent after staging; writing it from the staged symbols" >&2
  if [[ ! -d "${STAGED_BARS_DIR}" ]]; then
    echo "error: ${STAGED_BARS_DIR} has no staged bars; lake-backfill wrote nothing" >&2
    exit 1
  fi
  STAGED_SYMBOLS="$(find "${STAGED_BARS_DIR}" -mindepth 1 -maxdepth 1 -type d -name 'symbol=*' -printf '%f\n' | sed 's/^symbol=//' | sort)"
  if [[ -z "${STAGED_SYMBOLS}" ]]; then
    echo "error: ${STAGED_BARS_DIR} has no symbol directories; lake-backfill wrote nothing" >&2
    exit 1
  fi
  python3 -I -c '
import json, sys
symbols = [line for line in sys.argv[1].splitlines() if line]
with open(sys.argv[2], "w", encoding="utf-8") as fh:
    json.dump({"symbols": symbols}, fh, indent=2, sort_keys=True)
    fh.write("\n")
' "${STAGED_SYMBOLS}" "${UNIVERSE_JSON}"
fi

# Each derivs backfill runs on its own catch-up window, outside the bars
# check above, so a run stopped by a derivs failure is retried after the bars
# are staged and the retry still fetches the derivs. The window starts the
# day after the first symbol's latest staged day for that stream (the bars
# window when nothing is staged), but never later than DERIVS_RECHECK_DAYS
# before yesterday: one symbol can fail on a day the first symbol succeeded
# on, and a retry keyed on the first symbol alone would call that day staged.
# Already-written days are never rewritten.
#
# A day that is not complete yet is not a failure in either source: REST
# writes only closed days and answers an empty page for a delisted perp, and
# the archive answers HTTP 404 for an unpublished file; both exit 0. So a
# non-zero exit is a real failure (a refused argument, an unexpected error, or
# a request that failed its retries, status, checksum or parse), and it stops
# the run before a book is scored on incomplete data.
DERIVS_RECHECK_DAYS=3
RECHECK_FIRST="$(date -u -d "${LAST} -$((DERIVS_RECHECK_DAYS - 1)) days" +%Y-%m-%d)"

derivs_first() {
  local stream="$1" first="${FIRST}" latest=""
  if [[ -n "${FIRST_SYMBOL:-}" ]]; then
    latest="$(find "${SHADOW_LAKE}/staging/${stream}/symbol=${FIRST_SYMBOL}" -mindepth 1 -maxdepth 1 -type d -name 'date=*' -printf '%f\n' 2>/dev/null | sed 's/^date=//' | sort | tail -n1)"
  fi
  if [[ -n "${latest}" ]]; then
    first="$(date -u -d "${latest} +1 day" +%Y-%m-%d)"
  fi
  if [[ "${first}" > "${RECHECK_FIRST}" ]]; then
    first="${RECHECK_FIRST}"
  fi
  printf '%s\n' "${first}"
}

run_derivs() {
  local label="$1"; shift
  local status
  set +e
  LAKE="${SHADOW_LAKE}" "${RUN_SH}" lake-derivs-backfill "$@"
  status=$?
  set -e
  if [[ "${status}" -ne 0 ]]; then
    echo "error: lake-derivs-backfill (${label}) exited ${status}; stopping before the book step" >&2
    exit "${status}"
  fi
}

DERIVS_FIRST="$(derivs_first futbars)"
log "step 2/6: lake-derivs-backfill --streams funding,futbars --source rest, over ${DERIVS_FIRST}..${LAST}"
run_derivs "funding,futbars" --first "${DERIVS_FIRST}" --last "${LAST}" \
  --symbols-from "${UNIVERSE_JSON}" --streams funding,futbars --source rest

if [[ "${SHADOW_METRICS}" == "1" ]]; then
  METRICS_FIRST="$(derivs_first metrics)"
  log "step 2/6: lake-derivs-backfill --streams metrics --source archive, over ${METRICS_FIRST}..${LAST}"
  run_derivs "metrics" --first "${METRICS_FIRST}" --last "${LAST}" \
    --symbols-from "${UNIVERSE_JSON}" --streams metrics
fi

# -- step 3: lake-seal -----------------------------------------------------------

log "step 3/6: lake-seal"
SEAL_OUTPUT="$(LAKE="${SHADOW_LAKE}" "${RUN_SH}" lake-seal)"
echo "${SEAL_OUTPUT}"
SNAPSHOT_PATH="$(python3 -I -c '
import json, sys
print(json.loads(sys.argv[1])["path"])
' "${SEAL_OUTPUT}")"

# -- step 4: prune old snapshots --------------------------------------------------

log "step 4/6: prune snapshots, keeping the newest ${SHADOW_KEEP}"
SNAPSHOTS_DIR="${SHADOW_LAKE}/snapshots"
if [[ -d "${SNAPSHOTS_DIR}" ]]; then
  mapfile -t ALL_SNAPSHOTS < <(find "${SNAPSHOTS_DIR}" -mindepth 1 -maxdepth 1 -type d \
    -regextype posix-extended \
    -regex '.*/[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z_[0-9a-f]{6}' \
    -printf '%f\n' | sort -r)
  if [[ "${#ALL_SNAPSHOTS[@]}" -gt "${SHADOW_KEEP}" ]]; then
    for name in "${ALL_SNAPSHOTS[@]:${SHADOW_KEEP}}"; do
      echo "  removing old snapshot ${name}" >&2
      # lake-seal leaves every directory r-x, and unlinking needs write on
      # the parent, so a sealed snapshot must be made writable to be removed.
      chmod -R u+w -- "${SNAPSHOTS_DIR:?}/${name}"
      rm -rf -- "${SNAPSHOTS_DIR:?}/${name}"
    done
  fi
fi

# -- step 5: fetch the public BingX contracts document ----------------------------

log "step 5/6: fetch the BingX contracts document"
CONTRACTS_PATH="${SHADOW_LAKE}/contracts.json"
curl -fsSL "https://open-api-vst.bingx.com/openApi/swap/v2/quote/contracts" -o "${CONTRACTS_PATH}"
# The ticker lets shadow-book drop a symbol whose BingX price is more than 2x
# from the lake's perp close: a different coin under the same ticker name.
TICKER_PATH="${SHADOW_LAKE}/ticker.json"
curl -fsSL "https://open-api-vst.bingx.com/openApi/swap/v2/quote/ticker" -o "${TICKER_PATH}"

# -- step 6: rebuild the book -----------------------------------------------------

log "step 6/6: shadow-book --snapshot ${SNAPSHOT_PATH} --out ${SHADOW_OUT}"

NODE_ARGS=()
# Metrics land a few hours after the bars; without this the decision date
# could run ahead of them and the hold rule would freeze a book scored on a
# missing metrics day.
if [[ "${SHADOW_METRICS}" == "1" ]]; then
  NODE_ARGS+=(--require-stream metrics)
fi
while IFS= read -r line || [[ -n "${line}" ]]; do
  line="${line%$'\r'}"
  [[ -z "${line}" ]] && continue
  [[ "${line}" == \#* ]] && continue
  NODE_ARGS+=(--node "${line}")
done < "${SHADOW_NODES}"

if [[ "${#NODE_ARGS[@]}" -eq 0 ]]; then
  echo "error: ${SHADOW_NODES} has no CAMPAIGN_ID/NODE_ID lines" >&2
  exit 1
fi

BOOK_LINE="$("${RUN_SH}" shadow-book \
  --snapshot "${SNAPSHOT_PATH}" \
  --out "${SHADOW_OUT}" \
  --contracts "${CONTRACTS_PATH}" \
  --ticker "${TICKER_PATH}" \
  "${NODE_ARGS[@]}")"
echo "${BOOK_LINE}"

# Keep every book as written (book_id = shadow-<decision date>-<nodes hash>),
# so the forward evaluation can rebuild exactly what was traded.
HISTORY_DIR="$(dirname "${SHADOW_OUT}")/history"
mkdir -p "${HISTORY_DIR}"
BOOK_ID="$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["book_id"])' "${SHADOW_OUT}")"
if [[ ! -f "${HISTORY_DIR}/${BOOK_ID}.json" ]]; then
  cp -- "${SHADOW_OUT}" "${HISTORY_DIR}/${BOOK_ID}.json"
fi
printf '%s\n' "${BOOK_LINE}" >> "${HISTORY_DIR}/shadow-book.jsonl"

# -- the one-time switchover (docs/preregistration/2026-10-15-shadow-v1.md) ------
# With SHADOW_START set, hand the VST rebalance bot over from the fixture book
# once the first book on or after SHADOW_START exists (a no-op afterwards).
if [[ -n "${SHADOW_START:-}" ]]; then
  SHADOW_OUT="${SHADOW_OUT}" "$(dirname "${BASH_SOURCE[0]}")/shadow_switch.sh"
fi
