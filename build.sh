#!/usr/bin/env bash
set -euo pipefail

# Bruk: ./build.sh v0.1.0
if [[ $# -lt 1 ]]; then
  echo "Bruk: $0 <versjon>    (f.eks. $0 v0.1.0)" >&2
  exit 1
fi

TAG="$1"

# Finn modulnavn fra mappen skriptet ligger i
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_NAME="$(basename "$SCRIPT_DIR")"

# Enkle defaults (kan overstyres via miljøvariabler)
IMAGE_PREFIX="${IMAGE_PREFIX:-llsynit}"
IMAGE="${IMAGE_PREFIX}/${MODULE_NAME}"
PLATFORMS="${PLATFORMS:-linux/amd64,linux/arm64}"
DOCKERFILE="${DOCKERFILE:-${SCRIPT_DIR}/Dockerfile}"

if [[ ! -f "$DOCKERFILE" ]]; then
  echo "Fant ikke Dockerfile: $DOCKERFILE" >&2
  exit 2
fi

echo "==> Bygger ${IMAGE}:${TAG} (+ latest) for ${PLATFORMS}"
# Sørg for at buildx finnes (gjør ingenting hvis den allerede eksisterer)
docker buildx create --use --name multi >/dev/null 2>&1 || docker buildx use multi >/dev/null 2>&1 || true

docker buildx build \
  --platform "$PLATFORMS" \
  -t "${IMAGE}:${TAG}" \
  -t "${IMAGE}:latest" \
  -f "$DOCKERFILE" \
  "$SCRIPT_DIR" --push

echo "✅ Pushet:"
echo "   - ${IMAGE}:${TAG}"
echo "   - ${IMAGE}:latest"
