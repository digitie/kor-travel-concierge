#!/usr/bin/env bash
# 단일 호스트 Docker Compose 라이브 실행 (Linux / WSL2)
#
# `docker compose up --build`로 rustfs / api / mcp / scheduler / frontend를 함께
# 띄운다. Windows 사용자는 WSL2(Ubuntu) 안의 Docker Engine 또는 Docker Desktop
# WSL backend에서 이 스크립트를 실행한다.
#
# 기본 host port: API 8000, Frontend 3000, MCP 8010, RustFS 9003/9004.
# host port를 바꾸려면 API_HOST_PORT 등 환경 변수를 지정한다.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker CLI를 찾을 수 없습니다. WSL2(Ubuntu) 안에서 Docker Engine 또는 Docker Desktop WSL backend를 설치하십시오." >&2
  exit 1
fi

exec docker compose up --build "$@"
