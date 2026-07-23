#!/usr/bin/env bash
set -euo pipefail

# Bruk:
#   ./build.sh v0.1.20
#
# Valgfritt:
#   NO_CACHE=0 ./build.sh v0.1.20
#   PLATFORMS=linux/arm64 ./build.sh v0.1.20

if [[ $# -ne 1 ]]; then
  echo "Bruk: $0 <versjon>    (f.eks. $0 v0.1.20)" >&2
  exit 1
fi

TAG="$1"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_NAME="$(basename "$SCRIPT_DIR")"

IMAGE_PREFIX="${IMAGE_PREFIX:-llsynit}"
IMAGE="${IMAGE_PREFIX}/${MODULE_NAME}"
PLATFORMS="${PLATFORMS:-linux/amd64,linux/arm64}"
DOCKERFILE="${DOCKERFILE:-${SCRIPT_DIR}/Dockerfile}"
BUILDER_NAME="${BUILDER_NAME:-multi}"
NO_CACHE="${NO_CACHE:-1}"

if [[ ! -f "$DOCKERFILE" ]]; then
  echo "Fant ikke Dockerfile: $DOCKERFILE" >&2
  exit 2
fi

if [[ ! -f "${SCRIPT_DIR}/requirements.txt" ]]; then
  echo "Fant ikke requirements.txt i ${SCRIPT_DIR}" >&2
  exit 3
fi

BUILD_ARGS=(
  --pull
  --platform "$PLATFORMS"
  --tag "${IMAGE}:${TAG}"
  --tag "${IMAGE}:latest"
  --file "$DOCKERFILE"
  --push
)

if [[ "$NO_CACHE" == "1" ]]; then
  BUILD_ARGS+=(--no-cache)
fi

echo "==> Image:       ${IMAGE}"
echo "==> Tag:         ${TAG}"
echo "==> Platforms:   ${PLATFORMS}"
echo "==> Dockerfile:  ${DOCKERFILE}"
echo "==> No cache:    ${NO_CACHE}"

if ! docker buildx inspect "$BUILDER_NAME" >/dev/null 2>&1; then
  docker buildx create \
    --name "$BUILDER_NAME" \
    --driver docker-container \
    --use
else
  docker buildx use "$BUILDER_NAME"
fi

docker buildx inspect --bootstrap >/dev/null

docker buildx build \
  "${BUILD_ARGS[@]}" \
  "$SCRIPT_DIR"

echo
echo "✅ Pushet:"
echo "   - ${IMAGE}:${TAG}"
echo "   - ${IMAGE}:latest"
echo
echo "Skann med:"
echo "docker scout cves ${IMAGE}:${TAG}"
