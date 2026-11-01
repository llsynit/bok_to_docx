#!/usr/bin/env bash
set -euo pipefail

# Bruk:
#   ./build.sh v0.1.53
#
# Bygg fra ren Git-worktree:
#   MODULE_NAME=bok_to_docx ./build.sh v0.1.53
#
# Valgfrie miljøvariabler:
#   IMAGE_PREFIX=llsynit
#   MODULE_NAME=bok_to_docx
#   PLATFORMS=linux/amd64,linux/arm64
#   BUILDER_NAME=multi
#   NO_CACHE=1
#   PUSH=1
#   PUSH_LATEST=0
#   REQUIRE_CLEAN_GIT=1
#   DOCKERFILE=/path/to/Dockerfile

usage() {
    cat <<'EOF'
Bruk: ./build.sh <versjon>

Eksempel:
  ./build.sh v0.1.53

Fra en ren worktree:
  MODULE_NAME=bok_to_docx ./build.sh v0.1.53

Variabler:
  IMAGE_PREFIX       Docker Hub-bruker (llsynit)
  MODULE_NAME        Imagenavn (mappenavn som standard)
  PLATFORMS          linux/amd64,linux/arm64
  BUILDER_NAME       multi
  NO_CACHE           1 = uten cache (standard)
  PUSH               1 = publiser (standard)
  PUSH_LATEST        1 = publiser også latest
  REQUIRE_CLEAN_GIT  1 = krev ren Git-arbeidskopi
  DOCKERFILE         Alternativ Dockerfile

Eksempel:
  MODULE_NAME=bok_to_docx \
  PUSH_LATEST=1 \
  ./build.sh v0.1.53
EOF
}

if [[ $# -ne 1 ]]; then
    usage >&2
    exit 1
fi

TAG="$1"

if [[ ! "$TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+([.-][a-zA-Z0-9.-]+)?$ ]]; then
    echo "Ugyldig versjon: $TAG" >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

IMAGE_PREFIX="${IMAGE_PREFIX:-llsynit}"
MODULE_NAME="${MODULE_NAME:-$(basename "$SCRIPT_DIR")}"
PLATFORMS="${PLATFORMS:-linux/amd64,linux/arm64}"
BUILDER_NAME="${BUILDER_NAME:-multi}"
DOCKERFILE="${DOCKERFILE:-${SCRIPT_DIR}/Dockerfile}"

NO_CACHE="${NO_CACHE:-1}"
PUSH="${PUSH:-1}"
PUSH_LATEST="${PUSH_LATEST:-0}"
REQUIRE_CLEAN_GIT="${REQUIRE_CLEAN_GIT:-1}"

IMAGE="${IMAGE_PREFIX}/${MODULE_NAME}"

for name in NO_CACHE PUSH PUSH_LATEST REQUIRE_CLEAN_GIT; do
    value="${!name}"
    if [[ "$value" != "0" && "$value" != "1" ]]; then
        echo "Ugyldig verdi for $name: $value (bruk 0 eller 1)" >&2
        exit 1
    fi
done

if [[ ! -f "$DOCKERFILE" ]]; then
    echo "Fant ikke Dockerfile: $DOCKERFILE" >&2
    exit 2
fi

if [[ ! -f "${SCRIPT_DIR}/requirements.txt" ]]; then
    echo "Fant ikke requirements.txt" >&2
    exit 3
fi

command -v docker >/dev/null || {
    echo "Docker er ikke installert." >&2
    exit 4
}

docker buildx version >/dev/null || {
    echo "Docker Buildx er ikke tilgjengelig." >&2
    exit 4
}

if [[ "$REQUIRE_CLEAN_GIT" == "1" ]]; then
    if ! git -C "$SCRIPT_DIR" rev-parse --is-inside-work-tree \
        >/dev/null 2>&1; then
        echo "Byggemappen er ikke en Git-arbeidskopi." >&2
        exit 5
    fi

    if [[ -n "$(git -C "$SCRIPT_DIR" status --porcelain)" ]]; then
        echo "Git-arbeidskopien har lokale endringer." >&2
        echo "Bruk en ren worktree før publisering." >&2
        exit 5
    fi
fi

GIT_COMMIT="unknown"

if git -C "$SCRIPT_DIR" rev-parse HEAD >/dev/null 2>&1; then
    GIT_COMMIT="$(git -C "$SCRIPT_DIR" rev-parse --short HEAD)"
fi

echo
echo "========================================"
echo " Docker Buildx"
echo "========================================"
echo "Image:       ${IMAGE}"
echo "Version:     ${TAG}"
echo "Platforms:   ${PLATFORMS}"
echo "Git commit:  ${GIT_COMMIT}"
echo "Dockerfile:  ${DOCKERFILE}"
echo "No cache:    ${NO_CACHE}"
echo "Push:        ${PUSH}"
echo "Push latest: ${PUSH_LATEST}"
echo "========================================"
echo

if ! docker buildx inspect "$BUILDER_NAME" >/dev/null 2>&1; then
    docker buildx create \
        --name "$BUILDER_NAME" \
        --driver docker-container
fi

docker buildx use "$BUILDER_NAME"
docker buildx inspect --bootstrap >/dev/null

BUILD_ARGS=(
    --pull
    --platform "$PLATFORMS"
    --tag "${IMAGE}:${TAG}"
    --file "$DOCKERFILE"
    --label "org.opencontainers.image.revision=${GIT_COMMIT}"
)

if [[ "$NO_CACHE" == "1" ]]; then
    BUILD_ARGS+=(--no-cache)
fi

if [[ "$PUSH_LATEST" == "1" ]]; then
    BUILD_ARGS+=(--tag "${IMAGE}:latest")
fi

if [[ "$PUSH" == "1" ]]; then
    BUILD_ARGS+=(--push)
else
    if [[ "$PLATFORMS" == *,* ]]; then
        echo "Lokalt bygg støtter her kun én plattform." >&2
        echo "Sett PLATFORMS=linux/arm64 eller linux/amd64." >&2
        exit 6
    fi
    BUILD_ARGS+=(--load)
fi

docker buildx build \
    "${BUILD_ARGS[@]}" \
    "$SCRIPT_DIR"

echo
echo "========================================"
echo " Bygg fullført"
echo "========================================"
echo "Image: ${IMAGE}:${TAG}"

if [[ "$PUSH" == "1" ]]; then
    echo "Publisert til Docker Hub."
    if [[ "$PUSH_LATEST" == "1" ]]; then
        echo "Også publisert: ${IMAGE}:latest"
    fi
else
    echo "Bygget lokalt, ikke publisert."
fi

echo
echo "Sikkerhetsskanning:"
echo "  docker scout cves ${IMAGE}:${TAG}"

