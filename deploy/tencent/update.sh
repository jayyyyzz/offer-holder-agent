#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

cd "${PROJECT_ROOT}"

git pull --ff-only
docker compose -f docker-compose.tencent.yml up -d --build
docker compose -f docker-compose.tencent.yml ps
