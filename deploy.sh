#!/usr/bin/env bash

set -Eeuo pipefail

IMAGE_NAME="${IMAGE_NAME:-automation}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
IMAGE_REF="${IMAGE_NAME}:${IMAGE_TAG}"
IMAGE_PLATFORM="${IMAGE_PLATFORM:-linux/amd64}"
CONTAINER_NAME="${CONTAINER_NAME:-automation}"
REMOTE_HOST="${REMOTE_HOST:-jacob@100.103.224.99}"
REMOTE_DIR="${REMOTE_DIR:-~/automation}"
APP_PORT="${APP_PORT:-8000}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${SCRIPT_DIR}"
DOCKERFILE_PATH="${PROJECT_ROOT}/Dockerfile"
ENV_FILE="${PROJECT_ROOT}/.env"

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

require_cmd docker
require_cmd ssh
require_cmd scp

if [[ ! -f "${DOCKERFILE_PATH}" ]]; then
  echo "Missing Dockerfile: ${DOCKERFILE_PATH}" >&2
  exit 1
fi

echo "Building ${IMAGE_REF} for ${IMAGE_PLATFORM} locally"
docker buildx build --platform "${IMAGE_PLATFORM}" --load -t "${IMAGE_REF}" "${PROJECT_ROOT}"

echo "Preparing remote directory ${REMOTE_DIR} on ${REMOTE_HOST}"
ssh "${REMOTE_HOST}" "mkdir -p ${REMOTE_DIR}"

if [[ -f "${ENV_FILE}" ]]; then
  echo "Uploading environment file"
  scp "${ENV_FILE}" "${REMOTE_HOST}:${REMOTE_DIR}/.env"
else
  echo "No local .env found at ${ENV_FILE}; skipping upload"
fi

echo "Streaming image to remote Docker daemon"
docker save "${IMAGE_REF}" | ssh "${REMOTE_HOST}" "docker load"

echo "Restarting remote container ${CONTAINER_NAME}"
ssh "${REMOTE_HOST}" "
  docker rm -f ${CONTAINER_NAME} >/dev/null 2>&1 || true
  docker run -d \
    --name ${CONTAINER_NAME} \
    --restart unless-stopped \
    -p ${APP_PORT}:8000 \
    $(if [[ -f "${ENV_FILE}" ]]; then printf '%s' "--env-file ${REMOTE_DIR}/.env"; fi) \
    ${IMAGE_REF}
"

echo "Deployment complete"
echo "Remote app should be available on port ${APP_PORT}"
