#!/usr/bin/env bash
# run.sh — fengshui dev helper
# Usage: ./run.sh <command> [args...]
#
# Secret-bearing commands (wrapped in `op run` — Stripe / Anthropic /
# OpenAI / AWS / DB creds are present in process env):
#   ./run.sh forge   [args]     claw-forge with any args (default: no args)
#   ./run.sh state              start claw-forge state service (port 8420)
#   ./run.sh app                start FastAPI dev server (uvicorn --reload)
#   ./run.sh agent  "desc"      run claw-forge with a feature description
#   ./run.sh migrate [head]     run alembic upgrade (default: head)
#   ./run.sh worker             start the report generation worker (Dramatiq + asyncpg pool)
#   ./run.sh test   [args]      run pytest
#   ./run.sh shell              drop into a shell with secrets injected
#   ./run.sh vst    [args]      python -m router.bingx_mirror with ONLY the BingX
#                               VST sub-account key (.env.vst.tpl), never .env.tpl
#   ./run.sh vst-rebalance [args]  one scheduled rebalance slot (systemd timer)
#   ./run.sh vst-flatten   [args]  cancel all orders and close all positions
#
# No-secret commands (run with a CLEAN env — package managers and linters
# must never see runtime credentials; this is the main supply-chain
# countermeasure for postinstall-style attacks):
#   ./run.sh stack              boot docker dev stack + emit per-service readiness
#   ./run.sh stack-down         stop the docker dev stack
#   ./run.sh install            uv sync (Python deps)
#   ./run.sh frontend-install   npm ci (in frontend/)
#   ./run.sh frontend-build     npm run build (in frontend/)
#   ./run.sh lint               ruff check . && mypy .
#   ./run.sh frontend-lint      npm run lint && npm run type-check
#   ./run.sh sbom               generate SBOM + run osv-scanner

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Playwright browsers: shared, and OUTSIDE ~/.cache.
#   - ~/.cache is read-only inside the agent sandbox (home_protection), so an
#     agent cannot install the pinned browser build to Playwright's default
#     location; it installs somewhere private and the acceptance gate, being a
#     separate process, never finds it.
#   - claw-forge >=0.8.110 otherwise defaults this to
#     <worktree>/.claw-forge/browsers, which is correct but re-downloads
#     ~650MB per worktree now that the Playwright e2e test runs inside every
#     task's whole-suite gate.
# One shared writable dir gives agent and gate the same browsers, fetched once.
export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-$HOME/.pw-browsers}"
ENV_TPL="${SCRIPT_DIR}/.env.tpl"
ENV_VST_TPL="${SCRIPT_DIR}/.env.vst.tpl"

cmd="${1:-help}"
shift || true

# ── Guards ────────────────────────────────────────────────────────────────────

# Only enforce 1Password / .env.tpl when the requested command needs secrets.
needs_secrets() {
  case "$1" in
    forge|state|agent|app|migrate|worker|test|shell) return 0 ;;
    *) return 1 ;;
  esac
}

if needs_secrets "${cmd}"; then
  if ! command -v op &>/dev/null; then
    echo "error: 1Password CLI (op) not found. Install via: brew install 1password-cli" >&2
    exit 1
  fi
  if [[ ! -f "${ENV_TPL}" ]]; then
    echo "error: ${ENV_TPL} not found." >&2
    exit 1
  fi
  if [[ -f "${SCRIPT_DIR}/.env" ]]; then
    echo "warning: plaintext .env file detected — remove it: rm ${SCRIPT_DIR}/.env" >&2
  fi
fi

# ── Wrapper ───────────────────────────────────────────────────────────────────

OP="op run --env-file=${ENV_TPL} --"

case "${cmd}" in

  # ── Secret-bearing commands ─────────────────────────────────────────────────

  forge)
    exec ${OP} claw-forge "$@"
    ;;

  state)
    echo "→ Starting claw-forge state service on port 8420..."
    exec ${OP} claw-forge state "$@"
    ;;

  agent)
    if [[ $# -eq 0 ]]; then
      echo "usage: ./run.sh agent \"feature description\"" >&2
      exit 1
    fi
    echo "→ Running agent: $*"
    exec ${OP} claw-forge run "$@"
    ;;

  app)
    # API_PORT is the single source of truth for the dev backend port, shared
    # with dev.sh and next.config's /api proxy default — so the frontend proxy
    # can't silently target a dead port (the "generating forever" footgun).
    echo "→ Starting FastAPI dev server on :${API_PORT:-8000} (hot-reload on app/, engine/, main.py)..."
    exec ${OP} uv run uvicorn main:app \
      --reload \
      --reload-dir app \
      --reload-dir engine \
      --reload-include 'main.py' \
      --host 0.0.0.0 --port "${API_PORT:-8000}" "$@"
    ;;

  migrate)
    target="${1:-head}"
    echo "→ Running alembic upgrade ${target}..."
    exec ${OP} uv run alembic upgrade "${target}"
    ;;

  worker)
    # CRITICAL: must invoke as `src.worker` (not `backend.src.worker`) from
    # cwd=backend/ with PYTHONPATH including the repo root.  Any other path
    # combination causes a silent double-import of `src.geo.engine` —
    # `configure_geo_pool()` writes to one module-globals copy,
    # `get_geo_pool()` reads None from another, and the GNAF address lookup
    # falls through to the Sydney-GPO stub (lat=-33.8688) instead of hitting
    # geo.addresses.  Symptom downstream: geo_fanout finds 0 roads → xuan_kong
    # raises OrchestratorPreconditionError("facing_direction absent in site_context").
    echo "→ Starting report-generation worker (cwd=backend/, module=src.worker)..."
    cd "${SCRIPT_DIR}/backend"
    exec ${OP} env PYTHONPATH="${SCRIPT_DIR}" uv run python -m src.worker "$@"
    ;;

  test)
    echo "→ Running tests..."
    exec ${OP} uv run pytest "$@"
    ;;

  shell)
    echo "→ Dropping into shell with secrets injected (type 'exit' to leave)..."
    exec ${OP} bash
    ;;

  vst)
    # The BingX VST mirror gets the sub-account key and nothing else: its own
    # env file, not .env.tpl, so no claw-forge agent ever sees an exchange key.
    # The placement store defaults to a file outside the repo.
    if [[ ! -f "${ENV_VST_TPL}" ]]; then
      echo "error: ${ENV_VST_TPL} not found." >&2
      exit 1
    fi
    mkdir -p "$HOME/.local/share/nullius"
    export DATABASE_URL="${DATABASE_URL:-sqlite:///$HOME/.local/share/nullius/vst.db}"
    cd "${SCRIPT_DIR}"
    exec op run --env-file="${ENV_VST_TPL}" -- \
      uv run --all-packages python -m router.bingx_mirror "$@"
    ;;

  vst-rebalance|vst-flatten)
    # Stage 2 entry points, with the same VST-only key and store as `vst`.
    if [[ ! -f "${ENV_VST_TPL}" ]]; then
      echo "error: ${ENV_VST_TPL} not found." >&2
      exit 1
    fi
    mkdir -p "$HOME/.local/share/nullius"
    export DATABASE_URL="${DATABASE_URL:-sqlite:///$HOME/.local/share/nullius/vst.db}"
    cd "${SCRIPT_DIR}"
    module="router.bingx_rebalance"; [[ "${cmd}" == "vst-flatten" ]] && module="router.bingx_flatten"
    exec op run --env-file="${ENV_VST_TPL}" -- \
      uv run --all-packages python -m "${module}" "$@"
    ;;

  # ── No-secret commands ──────────────────────────────────────────────────────
  # NEVER wrap these in `op run`. A compromised npm/pypi dep running during
  # install or lint must not see Stripe/Anthropic/OpenAI/AWS credentials.

  stack)
    exec bash "${SCRIPT_DIR}/scripts/dev-stack.sh"
    ;;

  stack-down)
    echo "→ Stopping dev stack..."
    exec docker compose -f "${SCRIPT_DIR}/docker-compose.yml" down
    ;;

  install)
    echo "→ uv sync (no secrets in env)..."
    exec uv sync "$@"
    ;;

  frontend-install)
    echo "→ npm ci in frontend/ (no secrets in env)..."
    cd "${SCRIPT_DIR}/frontend"
    exec npm ci "$@"
    ;;

  frontend-build)
    echo "→ npm run build in frontend/ (no secrets in env)..."
    cd "${SCRIPT_DIR}/frontend"
    exec npm run build "$@"
    ;;

  lint)
    echo "→ ruff + mypy (no secrets in env)..."
    uv run ruff check .
    exec uv run mypy .
    ;;

  frontend-lint)
    echo "→ npm lint + type-check in frontend/ (no secrets in env)..."
    cd "${SCRIPT_DIR}/frontend"
    npm run lint
    exec npm run type-check
    ;;

  sbom)
    echo "→ generating SBOM + scanning advisories (no secrets in env)..."
    cd "${SCRIPT_DIR}/frontend"
    npm audit signatures || true
    npx --yes @cyclonedx/cyclonedx-npm --output-file "${SCRIPT_DIR}/frontend-sbom.json"
    npx --yes osv-scanner --lockfile=package-lock.json
    ;;

  help|--help|-h)
    grep '^#' "${BASH_SOURCE[0]}" | grep -E '^\s*#\s+\.' | sed 's/^#//'
    ;;

  *)
    echo "error: unknown command '${cmd}'. Run ./run.sh help for usage." >&2
    exit 1
    ;;

esac
