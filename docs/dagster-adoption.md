# Concierge 공용 Dagster 적용·복구

## 구성과 소유권

Manager의 공용 webserver/daemon/metadata instance를 Map·PinVi·Geo와 함께 사용한다.
Concierge는 `ktc.dagster.definitions` code location(gRPC `12603`)만 제공한다.
API/MCP 이미지에는 Dagster SDK를 설치하지 않는다. 관리자 summary는 내부 GraphQL을
Common bounded HTTP로 조회하며 공개 URL은 브라우저 링크에만 사용한다.
Common Python은 `efcd671207d7f9e2fb01251bab6854a8d543279a`, UI는 vendored dev.6을 사용한다.

수집 identity·payload·멱등 적재·사용자 중지·재시작 이력은 기존 `crawl_runs`가 소유한다.
native run은 owner ID·retry·attempt·control generation으로 특정 domain attempt를 claim한다.
paid provider 실패는 native FAILURE와 domain failed로 끝내고 자동 provider 재호출을 하지 않는다.
worker crash와 시간 초과는 terminal metadata, stale heartbeat, physical execution lease가 모두
확인된 뒤 최대 3회 domain 재시도한다. 정상 SIGTERM은 retry를 소모하지 않고 attempt만 바꾼다.
explicit native/domain cancel은 cancelled로 끝내며 자동 부활하지 않는다.
시간 초과의 CANCELING→FAILURE 경합은 실제 native 시작 시각·runtime tag로 판별한다.
metadata UNKNOWN에서는 owner를 보존하며 cursor는 다음 행으로 진행한다.

## 전환 절차

1. 기존 APScheduler 바이너리를 먼저 중지하고 실행 작업을 drain한다. 새 DB fence는 이전 바이너리를
   바꿀 수 없으므로 기존 실행자를 켠 채 모드를 전환하지 않는다. domain과 native 활성 작업을 함께 확인한다.
2. Concierge migration을 `python -m alembic upgrade head`로 적용한다. 초기 mode는 `legacy`, generation은 0이다.
   shared metadata schema는 Manager의 정식 storage migrate one-shot으로 준비한다.
3. Manager의 `conc` 기본 target은 code server를 포함한다. old scheduler는 `legacy-scheduler` profile의
   rollback 정의로 남는다. code image와 공유 instance/workspace를 함께 반영한다.
4. Dagster code server의 shared instance 환경에서 CLI를 실행한다(API/MCP target에는 SDK가 없다).
   `python -m ktc.cli scheduler-backend`로 현재 backend/generation을 확인한다.
   같은 설정으로 `python -m ktc.cli scheduler-backend --activate dagster --expected-generation <현재 세대>`를 실행한다.
   CLI는 native NOT_STARTED/QUEUED/STARTING/STARTED/CANCELING, domain owned pending/running,
   metadata UNKNOWN 및 세대 불일치를 거부한다. drain 후 실패 원인을 해소하고 다시 실행한다.
5. shared daemon의 세 sensor, gRPC child load health, native/domain 결과, 로그인→대시보드→로그아웃을 확인한다.
   API internal URL은 `11002`, browser public URL은 `11001` gateway를 사용한다.

## 장애와 rollback

- failed/cancelled 작업은 기존 `/jobs/{id}` 재시작으로 새 lineage를 만든다. 유료 provider 오류는 원인을
  수정한 뒤 운영자가 재시작한다. retry 한도를 소진하면 attention 상태로 남는다.
- code server container가 재시작하면 Manager의 기존 location/incarnation reaper가 옛 native STARTED를
  실패로 마감한다. 이후 domain recovery가 물리 lease 소멸·heartbeat 만료를 확인한다.
  Docker unhealthy 표시 자체가 재시작을 보장한다고 가정하지 않는다.
- rollback도 native/domain drain 후 위 CLI에 `--activate legacy --expected-generation <현재 세대>`를 사용한다.
  Dagster 발화를 중단한 뒤 legacy profile을 명시적으로 실행한다. pending attempt는 세대 전환마다 증가한다.
  owned pending/running이 남으면 migration downgrade도 거부한다.

## 메모리와 실행 상한

code server는 2GiB, location 동시 실행은 2개, job마다 1개, multiprocess step은 1개다.
provider 예약은 호스트 UID의 안전한 private OFD 파일 네 슬롯(각 256MiB)으로 합산 1024MiB를
넘지 않는다. Whisper는 네 슬롯을 단독 사용하고 captions는 최대 세 개다. 1536MiB high-water에서
새 claim을 보류한다. 기본 native 상한은 21600초다.
stdlib guardian은 heavy import 전에 kernel PDEATHSIG(SIGKILL)과 독립 pipe watchdog을 설치해
provider가 C 연산 중이어도 guardian/worker hard kill 뒤 같은 group의 자식·손자를 회수한다.
pidfd Python wrapper가 없는 Linux 빌드에서는 libc wrapper를 사용하며 외부 PID group을 종료하지 않는다.
예약은 ETL 전체 RSS의 hard limit이나 Whisper 모델별 최대 메모리 증명을 대신하지 않는다.

## 재현 검증

개발 회귀 환경은 backend/etl/scheduler 및 `dagster/requirements.txt`를 함께 설치한다. API/MCP 배포 target에는 Dagster SDK를 설치하지 않는다.

- `PYTHONPATH=backend:. KTC_TEST_PG_DSN=<격리 PostGIS DSN> python -m pytest backend/tests`.
- `frontend`에서 `npm ci`, `npm run type-check`, `npm run lint`, `npm test`, `npm run build`.
- live 전용 `tests/e2e/dagster-common.spec.ts`: `KTC_LIVE_E2E=1`, `E2E_FRONTEND_URL`,
  `E2E_ADMIN_USERNAME`, `E2E_ADMIN_PASSWORD`, `E2E_DAGSTER_FAILURE_RUN`을 비공개 환경에서 제공한다.
  실제 native failure seed가 있어야 한다. API/schema와 브라우저 응답 주입 장애를 구분해 검증한다.
- 신규 API DTO의 OpenAPI 정본은 `docs/contracts/dagster-summary.openapi.json`이다.
  `PYTHONPATH=backend:. python scripts/export_dagster_contract.py --check`로 export 일치를 확인한다.
  TypeScript consumer는 `frontend/src/lib/dagster.ts`다.

2026-10-06 검증은 격리 DB/native runtime와 N150 Linux Chromium을 사용했다.
실제 운영 Concierge mode 전환·공개 gateway 배포·운영 Whisper RSS·유료 provider 호출은 NOT_RUN이다.
운영 접속 정보와 실행 로그/DSN은 local runbook/private receipt에만 보관한다.

metadata UNKNOWN의 lane 격리를 위해 dispatch cursor는 tick마다 시작 lane을 교대로 선택한다.
25초 전역 예산을 한 lane이 소진해도 다음 tick에서 다른 lane을 먼저 조회하고 각 keyset cursor를 보존한다.
