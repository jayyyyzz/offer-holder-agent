#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

cd "${PROJECT_ROOT}"

if [[ ! -f "deploy/tencent/app.env" ]]; then
  echo "Missing deploy/tencent/app.env"
  exit 1
fi

if [[ ! -f "deploy/tencent/caddy.env" ]]; then
  echo "Missing deploy/tencent/caddy.env"
  exit 1
fi

docker compose -f docker-compose.tencent.yml up -d --build
docker compose -f docker-compose.tencent.yml ps
