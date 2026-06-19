#!/usr/bin/env bash
# 단일 호스트 Docker Compose 라이브 실행 — 개발(dev) 환경 (Linux / WSL2)
#
# 별도 지시가 없으면 이 스크립트는 dev 환경(내부 127.0.0.1)을 의미한다.
# prod는 kor-travel-docker-manager가 공식 도메인으로 올린다(ADR-27/ADR-28). 이 스크립트는
# prod 배포용이 아니다.
#
# repo 고정 host port가 비어 있으면 api / mcp / scheduler / frontend를 함께 띄운다.
# 고정 포트가 이미 사용 중이면 **새 포트로 바꾸지 않고**, 강제 종료 여부를 사용자에게
# 물어본다(stop-fixed-ports.sh). 사용자가 거부하면 기동을 중지한다.
# RustFS는 별도 고정 Docker 서비스를 사용한다. Windows 사용자는 WSL2(Ubuntu) 안의
# Docker Engine 또는 Docker Desktop WSL backend에서 실행한다.
#
# 고정 host port(dev, 127.0.0.1): API 12601, Frontend 12605, MCP 12602.
# RustFS 고정 포트 12101/12105는 외부 서비스가 소유하므로 이 스크립트가 회수하지 않는다.
# 무인 환경에서 점유 포트를 묻지 않고 회수하려면 FORCE_KILL_PORTS=1을 준다.
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

# 고정 포트 점유 리스너 확인/정리. 점유 중이면 사용자에게 강제 종료를 물어보고,
# 거부하면(또는 무인+미확인) 비정상 종료하므로 여기서 기동을 중지한다(새 포트로 바꾸지 않음).
if ! "${SCRIPT_DIR}/stop-fixed-ports.sh" \
  "${API_HOST_PORT}" "${FRONTEND_HOST_PORT}" "${MCP_HOST_PORT}"; then
  echo "고정 포트 정리가 취소되어 dev 기동을 중지합니다. (이미 떠 있는 인스턴스를 그대로 둡니다.)" >&2
  exit 1
fi

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

# dev 환경은 prod와 같은 12xxx 고정 포트를 쓰되, 내부 주소(127.0.0.1)로 접속한다.
# (prod는 같은 12xxx host 포트를 공식 도메인 + 리버스 프록시로 노출한다 — ADR-27/ADR-28.)
cat <<EOF

[dev] 로컬 접속 주소 — 내부 127.0.0.1, 고정 12xxx 포트:
  API : http://127.0.0.1:${API_HOST_PORT}/health   (Swagger: http://127.0.0.1:${API_HOST_PORT}/docs)
  Web : http://127.0.0.1:${FRONTEND_HOST_PORT}
  MCP : http://127.0.0.1:${MCP_HOST_PORT}/mcp   (streamable-http)
  RustFS S3 API : http://127.0.0.1:${RUSTFS_HOST_PORT:-12101}   콘솔: http://127.0.0.1:${RUSTFS_CONSOLE_HOST_PORT:-12105}
prod 공식 도메인 운영은 kor-travel-docker-manager가 담당합니다(ADR-28).
EOF
