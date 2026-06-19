#!/usr/bin/env bash
# 고정 host port를 점유 중인 리스너를 (확인 후) 정리한다. — 개발(dev) 환경 전용 안전장치.
#
# 별도 지시가 없으면 이 repo의 실행/스크립트는 dev 환경(내부 127.0.0.1)을 의미한다.
# prod는 kor-travel-docker-manager가 공식 도메인으로 올린다(ADR-27/ADR-28).
#
# 정책:
#   - 이 repo 고정 포트(API 12601, Web 12605, MCP 12602)가 이미 사용 중이면
#     **새 포트로 바꾸지 않는다.**
#   - prod 인스턴스(kor-travel-docker-manager) 여부와 관계없이, 강제 종료 전에
#     반드시 사용자에게 확인을 묻는다.
#   - 사용자가 거부하면(기본값) 종료 코드 3으로 빠져나가, 호출자(start-live.sh)가
#     기동을 중지하게 한다.
#   - 무인(non-interactive) 환경에서 묻지 않고 종료하려면 FORCE_KILL_PORTS=1
#     (또는 인자 --yes/-y)를 준다. TTY가 없고 FORCE_KILL_PORTS도 없으면 안전하게
#     거부(코드 3)한다.
#
# `python-krtour-map`의 stop-fixed-ports.sh 패턴을 차용했다. Linux 프로세스(ss/fuser),
# 해당 포트를 publish 중인 Docker 컨테이너, Windows 리스너를 모두 점검한다.
# RustFS 12101/12105는 별도 고정 Docker 서비스가 소유하므로 기본 회수 대상이 아니다.
#
# 사용법: stop-fixed-ports.sh [--yes|-y] [PORT ...]
set -euo pipefail

ASSUME_YES="${FORCE_KILL_PORTS:-0}"
ports=()
for a in "$@"; do
  case "$a" in
    --yes | -y) ASSUME_YES=1 ;;
    *) ports+=("$a") ;;
  esac
done

if [[ "${#ports[@]}" -eq 0 ]]; then
  ports=(
    "${API_HOST_PORT:-12601}"
    "${FRONTEND_HOST_PORT:-12605}"
    "${MCP_HOST_PORT:-12602}"
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

# 1) 점유 현황 수집 (강제 종료 전에 먼저 전부 점검한다)
occupied_ports=()
declare -A occ_pids occ_containers occ_winpids
for port in "${ports[@]}"; do
  mapfile -t pids < <(find_pids_for_port "$port")
  mapfile -t containers < <(find_docker_containers_for_port "$port")
  mapfile -t winpids < <(find_windows_pids_for_port "$port")
  if [[ "${#pids[@]}" -eq 0 && "${#containers[@]}" -eq 0 && "${#winpids[@]}" -eq 0 ]]; then
    echo "port $port: no listener"
    continue
  fi
  occupied_ports+=("$port")
  occ_pids[$port]="${pids[*]:-}"
  occ_containers[$port]="${containers[*]:-}"
  occ_winpids[$port]="${winpids[*]:-}"
  echo "port $port: 사용 중 — pids[${pids[*]:-}] containers[${containers[*]:-}] windows[${winpids[*]:-}]"
done

if [[ "${#occupied_ports[@]}" -eq 0 ]]; then
  exit 0
fi

# 2) 점유된 포트가 있으면 강제 종료 여부를 확인한다 (새 포트로 바꾸지 않는다).
if [[ "$ASSUME_YES" != "1" ]]; then
  if [[ -t 0 ]]; then
    echo
    echo "위 고정 포트가 이미 사용 중입니다(개발 또는 prod 인스턴스일 수 있음)."
    echo "새 포트로 바꾸지 않습니다. 위 리스너를 강제 종료하고 계속할까요?"
    read -r -p "강제 종료 [y/N]: " reply
    case "$reply" in
      [yY] | [yY][eE][sS]) ;;
      *)
        echo "사용자가 강제 종료를 거부했습니다. 작업을 중지합니다." >&2
        exit 3
        ;;
    esac
  else
    echo "비대화형 실행이고 FORCE_KILL_PORTS=1(또는 --yes)가 없어 강제 종료하지 않습니다. 작업을 중지합니다." >&2
    exit 3
  fi
fi

# 3) 확인됨(or --yes): 점유 리스너를 종료한다.
for port in "${occupied_ports[@]}"; do
  read -r -a pids <<<"${occ_pids[$port]:-}"
  if [[ "${#pids[@]}" -gt 0 ]]; then
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

  read -r -a containers <<<"${occ_containers[$port]:-}"
  if [[ "${#containers[@]}" -gt 0 ]]; then
    echo "port $port: stopping Docker containers ${containers[*]}"
    docker stop "${containers[@]}" >/dev/null 2>&1 || true
  fi

  read -r -a winpids <<<"${occ_winpids[$port]:-}"
  if [[ "${#winpids[@]}" -gt 0 ]]; then
    echo "port $port: stopping Windows listeners ${winpids[*]}"
    for pid in "${winpids[@]}"; do
      taskkill.exe /PID "$pid" /F >/dev/null 2>&1 || true
    done
  fi
done
