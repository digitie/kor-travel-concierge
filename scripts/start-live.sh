#!/usr/bin/env bash
# 단일 호스트 Docker Compose 라이브 실행 (Linux / WSL2)
#
# repo 고정 host port를 점유한 리스너를 먼저 정리(재시작 대비)한 뒤
# api / mcp / scheduler / frontend를 함께 띄운다. RustFS는 별도 고정 Docker 서비스를 사용한다.
# Windows 사용자는 WSL2(Ubuntu) 안의 Docker Engine 또는 Docker Desktop WSL
# backend에서 실행한다.
#
# 고정 host port: API 12601, Frontend 12605, MCP 12602.
# RustFS 고정 포트 12101/12105는 외부 서비스가 소유하므로 이 스크립트가 회수하지 않는다.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

# .env의 host port 값을 읽어 정리 대상 포트를 맞춘다.
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source ./.env
  set +a
fi

API_HOST_PORT="${API_HOST_PORT:-12601}"
FRONTEND_HOST_PORT="${FRONTEND_HOST_PORT:-12605}"
MCP_HOST_PORT="${MCP_HOST_PORT:-12602}"
export API_HOST_PORT FRONTEND_HOST_PORT MCP_HOST_PORT

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker CLI를 찾을 수 없습니다. WSL2(Ubuntu) 안에서 Docker Engine 또는 Docker Desktop WSL backend를 설치하십시오." >&2
  exit 1
fi

# 고정 포트 점유 리스너 정리(이전 실행 잔여 프로세스/컨테이너 포함).
"${SCRIPT_DIR}/stop-fixed-ports.sh" \
  "${API_HOST_PORT}" "${FRONTEND_HOST_PORT}" "${MCP_HOST_PORT}"

# 기본 실행은 외부 RustFS를 사용한다. 이전 profile 실행에서 남은 내장 RustFS
# 컨테이너가 있으면 중지/제거하되 volume은 삭제하지 않는다.
case ",${COMPOSE_PROFILES:-}," in
  *,embedded-rustfs,*) ;;
  *)
    docker compose stop rustfs >/dev/null 2>&1 || true
    docker compose rm -f rustfs >/dev/null 2>&1 || true
    ;;
esac

# `up` 외 다른 compose 동작이 필요하면 인자로 넘긴다(예: down).
docker compose up -d --build "$@"
docker compose ps
