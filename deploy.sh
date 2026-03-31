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
COMPOSE_FILE="${PROJECT_ROOT}/compose.yml"
LOCAL_ENV_FILE="${PROJECT_ROOT}/.env"
TMP_ENV="$(mktemp)"

cleanup() {
  rm -f "${TMP_ENV}"
}

trap cleanup EXIT

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

if [[ ! -f "${COMPOSE_FILE}" ]]; then
  echo "Missing compose file: ${COMPOSE_FILE}" >&2
  exit 1
fi

cat >"${TMP_ENV}" <<EOF
IMAGE_REF=${IMAGE_REF}
CONTAINER_NAME=${CONTAINER_NAME}
APP_PORT=${APP_PORT}
EOF

if [[ -f "${LOCAL_ENV_FILE}" ]]; then
  cat "${LOCAL_ENV_FILE}" >>"${TMP_ENV}"
else
  echo "No local .env found at ${LOCAL_ENV_FILE}; deploying without app secrets"
fi

echo "Building ${IMAGE_REF} for ${IMAGE_PLATFORM} locally"
docker buildx build --platform "${IMAGE_PLATFORM}" --load -t "${IMAGE_REF}" "${PROJECT_ROOT}"

echo "Preparing remote directory ${REMOTE_DIR} on ${REMOTE_HOST}"
ssh "${REMOTE_HOST}" "mkdir -p ${REMOTE_DIR}"

echo "Uploading compose configuration"
scp "${COMPOSE_FILE}" "${REMOTE_HOST}:${REMOTE_DIR}/compose.yml"
scp "${TMP_ENV}" "${REMOTE_HOST}:${REMOTE_DIR}/.env"

echo "Streaming image to remote Docker daemon"
docker save "${IMAGE_REF}" | ssh "${REMOTE_HOST}" "docker load"

echo "Removing existing remote container ${CONTAINER_NAME}"
ssh "${REMOTE_HOST}" "docker rm -f ${CONTAINER_NAME} >/dev/null 2>&1 || true"

echo "Starting stack with docker compose"
ssh "${REMOTE_HOST}" "cd ${REMOTE_DIR} && docker compose up -d"

echo "Deployment complete"
echo "Remote app should be available on port ${APP_PORT}"
