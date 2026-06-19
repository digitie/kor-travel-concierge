#!/usr/bin/env bash
# 단일 호스트 Docker Compose smoke 검증 — 개발(dev) 환경 (Linux / WSL2)
#
# dev는 prod와 같은 고정 12xxx 포트를 쓰되 내부 주소 127.0.0.1로 검증한다.
# (prod 공식 도메인 운영은 kor-travel-docker-manager — ADR-27/ADR-28.)
# Compose를 빌드·기동하고 RustFS·API·Frontend health와 MCP 포트를 127.0.0.1로 확인한 뒤
# `api` 컨테이너 안에서 `scripts/verify_rustfs.py`로 RustFS 버킷/객체 저장을
# 검증하고, 기본적으로 `docker compose down`으로 정리한다.
#
# 고정 포트가 이미 사용 중이면 stop-fixed-ports.sh가 강제 종료 여부를 묻는다. 무인(CI)
# 실행에서 점유 포트를 묻지 않고 회수하려면 FORCE_KILL_PORTS=1을 준다(없으면 안전 중지).
#
# host port는 아래 고정값을 기본으로 사용하고, 검증 동작만 환경 변수로 조정한다.
#   PROJECT_NAME             Compose project 이름 (기본: kor-travel-concierge-verify)
#   RUSTFS_HOST_PORT         RustFS S3 API host port (기본: 12101)
#   RUSTFS_CONSOLE_HOST_PORT RustFS 콘솔 host port (기본: 12105)
#   API_HOST_PORT            FastAPI host port (기본: 12601)
#   MCP_HOST_PORT            MCP host port (기본: 12602)
#   FRONTEND_HOST_PORT       Next.js host port (기본: 12605)
#   SKIP_BUILD=1             이미지 빌드 단계 건너뛰기
#   KEEP_RUNNING=1           검증 후 컨테이너를 내리지 않고 유지
set -euo pipefail

PROJECT_NAME="${PROJECT_NAME:-kor-travel-concierge-verify}"
export RUSTFS_HOST_PORT="${RUSTFS_HOST_PORT:-12101}"
export RUSTFS_CONSOLE_HOST_PORT="${RUSTFS_CONSOLE_HOST_PORT:-12105}"
export RUSTFS_DOCKER_ENDPOINT="${RUSTFS_DOCKER_ENDPOINT:-http://host.docker.internal:${RUSTFS_HOST_PORT}}"
export API_HOST_PORT="${API_HOST_PORT:-12601}"
export MCP_HOST_PORT="${MCP_HOST_PORT:-12602}"
export FRONTEND_HOST_PORT="${FRONTEND_HOST_PORT:-12605}"
SKIP_BUILD="${SKIP_BUILD:-0}"
KEEP_RUNNING="${KEEP_RUNNING:-0}"

if [[ -z "${NEXT_PUBLIC_API_BASE_URL:-}" ]]; then
  # dev 검증은 내부 주소 127.0.0.1을 사용한다.
  export NEXT_PUBLIC_API_BASE_URL="http://127.0.0.1:${API_HOST_PORT}"
fi

# 저장소 루트로 이동 (이 스크립트는 scripts/ 아래에 있다)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

compose() {
  docker compose --project-name "${PROJECT_NAME}" "$@"
}

assert_docker_available() {
  if ! command -v docker >/dev/null 2>&1; then
    echo "Docker CLI를 찾을 수 없습니다. WSL2(Ubuntu) 안에서 Docker Engine 또는 Docker Desktop WSL backend를 설치하고 docker 명령이 PATH에 잡히는지 확인하십시오." >&2
    exit 1
  fi
}

wait_http() {
  local url="$1"
  local timeout="${2:-90}"
  local deadline=$(( $(date +%s) + timeout ))
  while (( $(date +%s) < deadline )); do
    if curl -fsS --max-time 3 "${url}" >/dev/null 2>&1; then
      echo "OK ${url}"
      return 0
    fi
    sleep 2
  done
  echo "HTTP 확인 실패: ${url}" >&2
  return 1
}

wait_tcp() {
  local host="$1"
  local port="$2"
  local timeout="${3:-90}"
  local deadline=$(( $(date +%s) + timeout ))
  while (( $(date +%s) < deadline )); do
    if (exec 3<>"/dev/tcp/${host}/${port}") 2>/dev/null; then
      exec 3>&- 3<&- || true
      echo "OK tcp://${host}:${port}"
      return 0
    fi
    sleep 2
  done
  echo "TCP 확인 실패: ${host}:${port}" >&2
  return 1
}

cleanup() {
  if [[ "${KEEP_RUNNING}" != "1" ]]; then
    compose down
  fi
}

assert_docker_available
trap cleanup EXIT

if [[ ! -f .env ]]; then
  echo ".env 파일이 없어 Compose 기본값과 코드 기본값으로 검증합니다."
fi

"${SCRIPT_DIR}/stop-fixed-ports.sh" "${API_HOST_PORT}" "${FRONTEND_HOST_PORT}" "${MCP_HOST_PORT}"

compose config --quiet

if [[ "${SKIP_BUILD}" != "1" ]]; then
  compose build api mcp scheduler frontend
fi

compose up -d api mcp scheduler frontend

# dev 검증은 내부 주소 127.0.0.1 + 고정 12xxx 포트로 확인한다.
wait_http "http://127.0.0.1:${RUSTFS_HOST_PORT}/health/live"
wait_http "http://127.0.0.1:${API_HOST_PORT}/health"
wait_http "http://127.0.0.1:${FRONTEND_HOST_PORT}"
wait_tcp "127.0.0.1" "${MCP_HOST_PORT}"

compose exec -T api python /app/scripts/verify_rustfs.py
compose ps
