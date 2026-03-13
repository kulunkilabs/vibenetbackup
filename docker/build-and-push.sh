#!/usr/bin/env bash
# Build VIBENetBackup Docker image and push to container registry.
# Run from the repo root:  bash docker/build-and-push.sh
# Or with a specific tag:  bash docker/build-and-push.sh 1.0

set -euo pipefail

REGISTRY="ghcr.io"
IMAGE="${REGISTRY}/kulunkilabs/vibenetbackup"
VERSION="${1:-latest}"

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "==> Building image: ${IMAGE}:${VERSION}"
docker build \
  --tag "${IMAGE}:${VERSION}" \
  --tag "${IMAGE}:latest" \
  "${REPO_ROOT}"

echo ""
echo "==> Logging in to ${REGISTRY}"
echo "    (enter your registry password or token when prompted)"
docker login "${REGISTRY}"

echo ""
echo "==> Pushing ${IMAGE}:${VERSION}"
docker push "${IMAGE}:${VERSION}"

echo "==> Pushing ${IMAGE}:latest"
docker push "${IMAGE}:latest"

echo ""
echo "Done. Users can now run:"
echo "  docker compose -f docker/image/docker-compose.yml up -d"
