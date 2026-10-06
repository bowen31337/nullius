#!/usr/bin/env bash
# provision_runtime.sh — build the read-only runtime root a gVisor signal
# bundle runs in (additions_spec_gvisor_executor.xml, NULLIUS_GVISOR_RUNTIME_ROOT).
#
# Usage: deploy/gvisor/provision_runtime.sh [ROOT]   (default /opt/nullius/gvisor-runtime)
#
# The root is a minimal Ubuntu 24.04 (noble) filesystem with python3 (3.12),
# the exact polars and pyarrow versions uv.lock pins (so a sandboxed signal
# scores the same as the evaluator's own environment), and the `contract`
# and `app` packages the child bootstrap imports. Nothing else: no pip, no
# numpy (the evaluator's environment has none), no shell tools beyond
# minbase. It is built in ROOT.new and swapped in atomically, owned by root;
# the OCI bundle mounts it read-only. A manifest of versions and a tree
# digest is written beside it as ROOT.manifest.json.
#
# bug_spec_gvisor_bind_boot.xml: rootless runsc cannot boot a sandbox whose
# bundle carries a bind mount, so the child bootstrap (orchestrator's
# _sandbox_child.py) is baked into the root at /sandbox_child.py — the same
# path orchestrator._oci_bundle.CHILD_BOOTSTRAP_PATH names — instead of
# being bind-mounted in at run time. Re-running this script refreshes it.
#
# additions_spec_gvisor_executor.xml / runtime-root manifest check:
# orchestrator._gvisor.GVisorSandbox reads ROOT.manifest.json at
# construction and recomputes tree_sha256 itself (orchestrator._gvisor
# ._tree_sha256), refusing to run agent code in a root whose contents don't
# hash to the manifest's value. Keep this script's digest pipeline and that
# function in agreement: same files (sha256sum's own "-type f", symlinks
# excluded), same per-file line shape ("<hex>  ./<relative path>\n", two
# spaces), same order (LC_ALL=C — plain codepoint order, so no locale can
# make this script and Python disagree on how "./a" and "./B" sort).
#
# Needs: sudo, debootstrap, uv, network access to the Ubuntu mirror and PyPI.
set -euo pipefail

ROOT="${1:-/opt/nullius/gvisor-runtime}"
MIRROR="${MIRROR:-http://archive.ubuntu.com/ubuntu/}"
SUITE=noble
REPO="${REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

pin() {  # the version uv.lock pins for package $1
  awk -v p="$1" '$0=="name = \""p"\"" {getline; gsub(/version = |"/, ""); print; exit}' "$REPO/uv.lock"
}
POLARS="$(pin polars)"; PYARROW="$(pin pyarrow)"
[[ -n "$POLARS" && -n "$PYARROW" ]] || { echo "error: polars/pyarrow not pinned in uv.lock" >&2; exit 1; }

echo "→ debootstrap $SUITE minbase + python3 into $ROOT.new"
sudo rm -rf "$ROOT.new"
sudo debootstrap --variant=minbase --include=python3 "$SUITE" "$ROOT.new" "$MIRROR"

SITE=usr/local/lib/python3.12/dist-packages
echo "→ wheels polars==$POLARS pyarrow==$PYARROW (cp312 manylinux, binary only)"
UV_CACHE_DIR="${UV_CACHE_DIR:-$REPO/.uv-cache}" uv pip install --quiet \
  --target "$STAGE/site" --python-version 3.12 \
  --python-platform x86_64-manylinux_2_28 --only-binary :all: \
  "polars==$POLARS" "pyarrow==$PYARROW"
mkdir -p "$STAGE/site/contract" "$STAGE/site/app"
cp -a "$REPO/packages/contract/src/contract/." "$STAGE/site/contract/"
cp -a "$REPO/src/app/." "$STAGE/site/app/"
find "$STAGE/site" -name __pycache__ -prune -exec rm -rf {} +
sudo mkdir -p "$ROOT.new/$SITE"
sudo cp -a "$STAGE/site/." "$ROOT.new/$SITE/"

# bug_spec_gvisor_bind_boot.xml: baked in, not bind-mounted — rootless runsc
# cannot boot a sandbox whose bundle carries any bind mount. This is the same
# path orchestrator._oci_bundle.CHILD_BOOTSTRAP_PATH names.
CHILD_RELPATH=sandbox_child.py
echo "→ bake the child bootstrap into the root at /$CHILD_RELPATH"
sudo cp -a "$REPO/packages/orchestrator/src/orchestrator/_sandbox_child.py" "$ROOT.new/$CHILD_RELPATH"
sudo chown root:root "$ROOT.new/$CHILD_RELPATH"
sudo chmod 0444 "$ROOT.new/$CHILD_RELPATH"
CHILD_DIGEST="$(sudo sha256sum "$ROOT.new/$CHILD_RELPATH" | cut -d' ' -f1)"

echo "→ trim caches, docs and locales"
sudo rm -rf "$ROOT.new"/var/cache/apt/* "$ROOT.new"/var/lib/apt/lists/* \
  "$ROOT.new"/usr/share/doc/* "$ROOT.new"/usr/share/man/* "$ROOT.new"/usr/share/locale/*
sudo chown -R root:root "$ROOT.new"

echo "→ verify imports with the bootstrap's flags (python3 -I) in a chroot"
sudo chroot "$ROOT.new" /usr/bin/python3 -I -c \
  "import polars, pyarrow, contract.payload, contract.signal, sys; print('ok', sys.version.split()[0], polars.__version__, pyarrow.__version__)"

# orchestrator._gvisor.GVisorSandbox recomputes this same digest at
# construction (orchestrator._gvisor._tree_sha256) and refuses to run a root
# whose contents don't hash to this value — LC_ALL=C pins the sort to plain
# codepoint order so it agrees with Python's own str sort, locale-independent.
DIGEST="$(cd "$ROOT.new" && sudo find . -type f -print0 | LC_ALL=C sort -z | sudo xargs -0 sha256sum | sha256sum | cut -d' ' -f1)"
PY="$(sudo chroot "$ROOT.new" /usr/bin/python3 -c 'import sys; print(sys.version.split()[0])')"
COMMIT="$(git -c safe.directory="$REPO" -C "$REPO" rev-parse HEAD)"
sudo tee "$ROOT.new.manifest.json" >/dev/null <<EOF
{"root": "$ROOT", "suite": "$SUITE", "python": "$PY", "polars": "$POLARS",
 "pyarrow": "$PYARROW", "contract_from_commit": "$COMMIT", "tree_sha256": "$DIGEST",
 "child_bootstrap_path": "/$CHILD_RELPATH", "child_bootstrap_sha256": "$CHILD_DIGEST",
 "built_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"}
EOF

echo "→ swap into place"
sudo rm -rf "$ROOT.old"
[[ -d "$ROOT" ]] && sudo mv "$ROOT" "$ROOT.old"
sudo mv "$ROOT.new" "$ROOT"
sudo mv "$ROOT.new.manifest.json" "$ROOT.manifest.json"
sudo rm -rf "$ROOT.old"
echo "✓ runtime root at $ROOT ($(sudo du -sh "$ROOT" | cut -f1)); manifest $ROOT.manifest.json"
