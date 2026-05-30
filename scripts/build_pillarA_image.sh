#!/usr/bin/env bash
# AOPSO Sprint 36 -- build script for the Pillar-A advisory Linux image.
#
# Builds a linux/amd64 image from deploy/pillarA_advisory/Dockerfile against
# the repo root as build context. Detects docker or podman; if neither is
# available the script reports "skipped_no_builder" and exits 0 so the
# Sprint-36 scorecard can record an honest "no builder" outcome (the in-
# process serving parity test still proves correctness without Docker).
#
# Usage:
#   scripts/build_pillarA_image.sh                       # build with defaults
#   scripts/build_pillarA_image.sh --tag my/repo:tag     # custom tag
#   scripts/build_pillarA_image.sh --digest-file out.txt # write digest sink

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DOCKERFILE="${REPO_ROOT}/deploy/pillarA_advisory/Dockerfile"
DEFAULT_TAG="aopso/pillara-advisory:sprint36-r0"
TAG="${DEFAULT_TAG}"
DIGEST_FILE=""
PLATFORM="linux/amd64"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --tag)         TAG="$2"; shift 2;;
        --digest-file) DIGEST_FILE="$2"; shift 2;;
        --platform)    PLATFORM="$2"; shift 2;;
        -h|--help)
            sed -n '1,30p' "$0"
            exit 0
            ;;
        *)
            echo "unknown arg: $1" >&2
            exit 2
            ;;
    esac
done

emit_skipped() {
    local reason="$1"
    echo "skipped_no_builder:${reason}"
    if [[ -n "${DIGEST_FILE}" ]]; then
        printf 'skipped_no_builder:%s\n' "${reason}" > "${DIGEST_FILE}"
    fi
    exit 0
}

if command -v docker >/dev/null 2>&1; then
    BUILDER="docker"
elif command -v podman >/dev/null 2>&1; then
    BUILDER="podman"
else
    emit_skipped "no docker or podman in PATH"
fi

# Both docker and podman accept --platform, but docker requires buildx for
# linux/amd64 builds on non-amd64 hosts. We use the simplest invocation
# that works on standard AMAX-image builders.
echo "+ ${BUILDER} build --platform=${PLATFORM} -f ${DOCKERFILE} -t ${TAG} ${REPO_ROOT}" >&2
"${BUILDER}" build \
    --platform "${PLATFORM}" \
    -f "${DOCKERFILE}" \
    -t "${TAG}" \
    "${REPO_ROOT}"

# Best-effort digest capture. docker images --no-trunc + inspect gives the
# image ID; podman is API-compatible. If digest capture fails we still
# report success on the build itself.
DIGEST=""
if "${BUILDER}" inspect --format='{{.Id}}' "${TAG}" >/dev/null 2>&1; then
    DIGEST="$("${BUILDER}" inspect --format='{{.Id}}' "${TAG}")"
fi

echo "image_tag=${TAG}"
echo "image_digest=${DIGEST:-unknown}"
if [[ -n "${DIGEST_FILE}" ]]; then
    printf '%s\n' "${DIGEST:-unknown}" > "${DIGEST_FILE}"
fi
