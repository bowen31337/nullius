#!/usr/bin/env bash
# One-time switchover of the BingX VST rebalance bot from the synthetic fixture
# book to the forward-shadow book (docs/preregistration/2026-10-15-shadow-v1.md).
#
# The rebalance unit trades whatever ACTIVE_BOOK points at. ACTIVE_BOOK starts
# as a symlink to the fixture. Once the shadow book's decision date is on or
# after SHADOW_START, this script:
#   1. closes every fixture position and order with `run.sh vst-flatten
#      --confirm`, one of the two closing paths CLAUDE.md allows, so no fixture
#      position contaminates the shadow's P&L
#   2. repoints ACTIVE_BOOK at the shadow book
#   3. records the switch instant in SWITCHED_MARK
# After that it does nothing. It is VST only, through .env.vst.tpl.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_SH="${SCRIPT_DIR}/../../run.sh"
SHADOW_DIR="${SHADOW_DIR:-$HOME/.local/share/nullius/shadow}"
SHADOW_OUT="${SHADOW_OUT:-${SHADOW_DIR}/book.json}"
ACTIVE_BOOK="${ACTIVE_BOOK:-${SHADOW_DIR}/active_book.json}"
SWITCHED_MARK="${SHADOW_DIR}/switched_at"
SHADOW_START="${SHADOW_START:?SHADOW_START (YYYY-MM-DD) must be set}"

log() { echo "$(date -u +%FT%TZ) shadow-switch: $*" >&2; }

if [[ -f "${SWITCHED_MARK}" ]]; then
  log "already switched at $(cat "${SWITCHED_MARK}"); nothing to do"
  exit 0
fi
if [[ ! -f "${SHADOW_OUT}" ]]; then
  log "no shadow book at ${SHADOW_OUT} yet; staying on the fixture"
  exit 0
fi

BOOK_ID="$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["book_id"])' "${SHADOW_OUT}")"
DECISION_DATE="$(sed -E 's/^shadow-([0-9]{4}-[0-9]{2}-[0-9]{2})-.*/\1/' <<<"${BOOK_ID}")"
if [[ "${DECISION_DATE}" < "${SHADOW_START}" ]]; then
  log "shadow book ${BOOK_ID} predates SHADOW_START ${SHADOW_START}; staying on the fixture"
  exit 0
fi

log "switching to ${BOOK_ID}: flattening the fixture positions first"
"${RUN_SH}" vst-flatten --confirm
ln -sfn -- "${SHADOW_OUT}" "${ACTIVE_BOOK}"
date -u +%FT%TZ > "${SWITCHED_MARK}"
log "ACTIVE_BOOK now -> ${SHADOW_OUT}; the next rebalance slot trades ${BOOK_ID}"
