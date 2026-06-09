#!/usr/bin/env bash
# 고정 host port를 점유 중인 리스너를 정리한다(재시작 대비).
#
# `python-krtour-map`의 scripts/stop-fixed-ports.sh 패턴을 차용했다. Linux
# 프로세스(ss/fuser), 해당 포트를 publish 중인 Docker 컨테이너, WSL root 리스너,
# Windows 리스너(powershell.exe/taskkill.exe)를 모두 정리한다.
#
# 사용법: stop-fixed-ports.sh [PORT ...]
# 인자가 없으면 TripMate 고정 포트(API 9041, Web 9042, RustFS 9003/9004, MCP 8010)를 쓴다.
set -euo pipefail

ports=("$@")
if [[ "${#ports[@]}" -eq 0 ]]; then
  ports=(
    "${API_HOST_PORT:-9041}"
    "${FRONTEND_HOST_PORT:-9042}"
    "${RUSTFS_HOST_PORT:-9003}"
    "${RUSTFS_CONSOLE_HOST_PORT:-9004}"
    "${MCP_HOST_PORT:-8010}"
  )
fi

find_pids_for_port() {
  local port="$1"
  local ss_pids=""
  if command -v ss >/dev/null 2>&1; then
    ss_pids="$(
      ss -ltnp 2>/dev/null \
        | awk -v port="$port" '{ n=split($4, a, ":"); if (a[n] == port) print $0 }' \
        | sed -nE 's/.*pid=([0-9]+).*/\1/p'
    )"
  fi
  local fuser_pids=""
  if command -v fuser >/dev/null 2>&1; then
    fuser_pids="$(fuser -n tcp "$port" 2>/dev/null || true)"
  fi
  printf "%s\n%s\n" "$ss_pids" "$fuser_pids" | tr ' ' '\n' | sed '/^$/d' | sort -u
}

find_docker_containers_for_port() {
  local port="$1"
  if ! command -v docker >/dev/null 2>&1; then
    return 0
  fi
  docker ps --filter "publish=$port" --format "{{.ID}}" 2>/dev/null \
    | sed '/^$/d' | sort -u
}

find_windows_pids_for_port() {
  local port="$1"
  if ! command -v powershell.exe >/dev/null 2>&1; then
    return 0
  fi
  powershell.exe -NoProfile -Command \
    "Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess" \
    2>/dev/null | tr -d '\r' | sed '/^$/d' | sort -u
}

for port in "${ports[@]}"; do
  mapfile -t pids < <(find_pids_for_port "$port")
  if [[ "${#pids[@]}" -eq 0 ]]; then
    echo "port $port: no listener"
  else
    echo "port $port: stopping ${pids[*]}"
    for pid in "${pids[@]}"; do
      kill "$pid" 2>/dev/null || true
    done
    sleep 0.5
    for pid in "${pids[@]}"; do
      if kill -0 "$pid" 2>/dev/null; then
        kill -9 "$pid" 2>/dev/null || true
      fi
    done
  fi

  mapfile -t docker_containers < <(find_docker_containers_for_port "$port")
  if [[ "${#docker_containers[@]}" -gt 0 ]]; then
    echo "port $port: stopping Docker containers ${docker_containers[*]}"
    docker stop "${docker_containers[@]}" >/dev/null 2>&1 || true
  fi

  mapfile -t win_pids < <(find_windows_pids_for_port "$port")
  if [[ "${#win_pids[@]}" -gt 0 ]]; then
    echo "port $port: stopping Windows listeners ${win_pids[*]}"
    for pid in "${win_pids[@]}"; do
      taskkill.exe /PID "$pid" /F >/dev/null 2>&1 || true
    done
  fi
done
