#!/usr/bin/env bash
# build_image.sh — build the frozen evaluator image (deploy/evaluator/Containerfile)
# with podman or buildah, and print the digest-pinned reference to put in
# NULLIUS_EVALUATOR_IMAGE (additions_spec_real_campaign_path.xml feature 6).
#
# Usage: deploy/evaluator/build_image.sh
#
# An image must name a commit: this refuses to build (exit 1) when the
# working tree carries uncommitted changes under any path the Containerfile
# COPYs in, because evaluator_hash would then pin bytes nobody can check out
# again. SOURCE_DATE_EPOCH is set to HEAD's commit time (not "now") and
# passed to the engine's --timestamp, so two builds of the same commit
# produce the same image. The image is tagged localhost/nullius-evaluator:
# <short-sha>, and the one line of output is the digest-pinned reference —
# never the tag, since evaluator_hash requires a digest (architecture §12,
# §16).
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO"

# Exactly what the Containerfile COPYs from the workspace. A change outside
# this list (deploy/evaluator/* itself, another member, docs) does not block
# the build — only content this image's bytes actually depend on does.
COPIED_PATHS=(
  pyproject.toml
  uv.lock
  src/app
  packages/evaluator/pyproject.toml
  packages/evaluator/src
  packages/cost-model/pyproject.toml
  packages/cost-model/src
  packages/contract/pyproject.toml
  packages/contract/src
  packages/snapshot/pyproject.toml
  packages/snapshot/src
  packages/nulloracle/pyproject.toml
  packages/nulloracle/src
)

dirty="$(git status --porcelain -- "${COPIED_PATHS[@]}")"
if [[ -n "$dirty" ]]; then
  echo "error: uncommitted changes under a path this image copies — an image must name a commit:" >&2
  echo "$dirty" >&2
  exit 1
fi

if command -v podman >/dev/null 2>&1; then
  ENGINE=podman
elif command -v buildah >/dev/null 2>&1; then
  ENGINE=buildah
else
  echo "error: neither podman nor buildah found on PATH (docker is not supported)" >&2
  exit 1
fi

SOURCE_DATE_EPOCH="$(git log -1 --format=%ct HEAD)"
export SOURCE_DATE_EPOCH
SHORT_SHA="$(git rev-parse --short HEAD)"
IMAGE_TAG="localhost/nullius-evaluator:${SHORT_SHA}"

echo "→ building ${IMAGE_TAG} with ${ENGINE} (SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH})" >&2
"$ENGINE" build \
  --timestamp "$SOURCE_DATE_EPOCH" \
  -f deploy/evaluator/Containerfile \
  -t "$IMAGE_TAG" \
  "$REPO"

# podman and buildah both compute the manifest digest for a purely local
# image at build time (containers/storage is content-addressed; unlike
# classic Docker's graph driver, neither engine waits for a registry push
# to know it) — but each engine exposes it through its own query, so the
# field is read with whichever engine did the build.
if [[ "$ENGINE" == podman ]]; then
  DIGEST="$(podman image inspect --format '{{.Digest}}' "$IMAGE_TAG")"
else
  DIGEST="$(buildah images --format '{{.Digest}}' "$IMAGE_TAG")"
fi

if [[ -z "$DIGEST" || "$DIGEST" != sha256:* ]]; then
  echo "error: ${ENGINE} did not report a sha256 digest for ${IMAGE_TAG}" >&2
  exit 1
fi

echo "localhost/nullius-evaluator@${DIGEST}"
