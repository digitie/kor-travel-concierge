#!/usr/bin/env bash
# 단일 호스트 Docker Compose 라이브 실행 (Linux / WSL2)
#
# 고정 host port를 점유한 리스너를 먼저 정리(재시작 대비)한 뒤
# rustfs / api / mcp / scheduler / frontend를 함께 띄운다.
# Windows 사용자는 WSL2(Ubuntu) 안의 Docker Engine 또는 Docker Desktop WSL
# backend에서 실행한다.
#
# 고정 host port: API 9041, Frontend 9042, MCP 8010, RustFS 9003/9004.
# 포트를 바꾸려면 .env 또는 환경 변수(API_HOST_PORT 등)를 지정한다.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

# .env의 host port override를 읽어 정리 대상 포트를 맞춘다.
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source ./.env
  set +a
fi

API_HOST_PORT="${API_HOST_PORT:-9041}"
FRONTEND_HOST_PORT="${FRONTEND_HOST_PORT:-9042}"
RUSTFS_HOST_PORT="${RUSTFS_HOST_PORT:-9003}"
RUSTFS_CONSOLE_HOST_PORT="${RUSTFS_CONSOLE_HOST_PORT:-9004}"
MCP_HOST_PORT="${MCP_HOST_PORT:-8010}"
export API_HOST_PORT FRONTEND_HOST_PORT RUSTFS_HOST_PORT RUSTFS_CONSOLE_HOST_PORT MCP_HOST_PORT

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker CLI를 찾을 수 없습니다. WSL2(Ubuntu) 안에서 Docker Engine 또는 Docker Desktop WSL backend를 설치하십시오." >&2
  exit 1
fi

# 고정 포트 점유 리스너 정리(이전 실행 잔여 프로세스/컨테이너 포함).
"${SCRIPT_DIR}/stop-fixed-ports.sh" \
  "${API_HOST_PORT}" "${FRONTEND_HOST_PORT}" \
  "${RUSTFS_HOST_PORT}" "${RUSTFS_CONSOLE_HOST_PORT}" "${MCP_HOST_PORT}"

# `up` 외 다른 compose 동작이 필요하면 인자로 넘긴다(예: down).
docker compose up -d --build "$@"
docker compose ps
