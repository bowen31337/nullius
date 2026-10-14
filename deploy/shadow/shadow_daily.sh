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
#   2. lake-backfill (bars), then lake-derivs-backfill (funding, futbars,
#      optionally metrics) over that window
#   3. lake-seal
#   4. prune every snapshot but the newest SHADOW_KEEP
#   5. fetch the public BingX contracts document (no key)
#   6. run.sh shadow-book, one --node per SHADOW_NODES line
#
# The script exits with the first failing step's code — except
# lake-derivs-backfill reading a day the archive has not published yet,
# which is tolerated: the run continues, and the book step (feature 3) picks
# the latest complete date on its own.

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
  log "step 2/6: already staged through ${LAST}; nothing to backfill"
else
  DERIVS_STREAMS="funding,futbars"
  if [[ "${SHADOW_METRICS}" == "1" ]]; then
    DERIVS_STREAMS="${DERIVS_STREAMS},metrics"
  fi
  log "step 2/6: lake-backfill, then lake-derivs-backfill --streams ${DERIVS_STREAMS}, over ${FIRST}..${LAST}"

  LAKE="${SHADOW_LAKE}" "${RUN_SH}" lake-backfill --first "${FIRST}" --last "${LAST}" "${BARS_SOURCE_ARGS[@]}"

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

  set +e
  LAKE="${SHADOW_LAKE}" "${RUN_SH}" lake-derivs-backfill --first "${FIRST}" --last "${LAST}" \
    --symbols-from "${UNIVERSE_JSON}" --streams "${DERIVS_STREAMS}"
  derivs_status=$?
  set -e
  if [[ "${derivs_status}" -ne 0 ]]; then
    echo "lake-derivs-backfill exited ${derivs_status}: a day the archive has not published yet is tolerated — continuing" >&2
  fi
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
      rm -rf -- "${SNAPSHOTS_DIR:?}/${name}"
    done
  fi
fi

# -- step 5: fetch the public BingX contracts document ----------------------------

log "step 5/6: fetch the BingX contracts document"
CONTRACTS_PATH="${SHADOW_LAKE}/contracts.json"
curl -fsSL "https://open-api-vst.bingx.com/openApi/swap/v2/quote/contracts" -o "${CONTRACTS_PATH}"

# -- step 6: rebuild the book -----------------------------------------------------

log "step 6/6: shadow-book --snapshot ${SNAPSHOT_PATH} --out ${SHADOW_OUT}"

NODE_ARGS=()
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

exec "${RUN_SH}" shadow-book \
  --snapshot "${SNAPSHOT_PATH}" \
  --out "${SHADOW_OUT}" \
  --contracts "${CONTRACTS_PATH}" \
  "${NODE_ARGS[@]}"
