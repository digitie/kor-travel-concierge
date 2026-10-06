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
2. Concierge migration을 저장소 루트에서 `python -m alembic upgrade head`로 적용한다. 초기 mode는 `legacy`, generation은 0이다.
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

활성 metadata 조회 UNKNOWN은 해당 job만 신규 발화를 보류한다. 다른 lane과 maintenance job은 계속 확인하고 cursor를 저장한다. 조회가 회복되면 보류한 job도 다시 발화할 수 있다. backend/generation 조회 UNKNOWN은 전체 발화를 계속 금지한다.


## 2026-10-07 운영 전환 결과와 실행 주의점

Concierge PR #242의 `1fe1f9f`와 Manager PR #463/#464의 `42ffc553`를 운영 호스트에 반영했다.
Manager의 기존 `rehearsal/rebuildable` 분류는 유지했다. 두 DB 백업, 이전 소스·이미지 복구 지점을
확보한 뒤 trusted installer와 canonical C6c 경로를 사용했다. APScheduler 중지·drain 후
`20261006_0030`으로 migration하고 공유 storage migrate 및 daemon/webserver를 갱신했다.
generation CLI의 결과는 `dagster / generation 1`이다. 기존 APScheduler는 중지 상태다.

- API 이미지의 기본 작업 디렉터리는 `/app/backend`다. 컨테이너 migration one-shot은
  Manager가 검증한 canonical projection에서 작업 디렉터리를 `/app`으로 지정하고
  `python -m alembic -c /app/alembic.ini upgrade head`를 실행한다. 기본 디렉터리에서 실행하면
  `No 'script_location' key found`로 DB 변경 전에 실패한다.
- 공개 Dagster 로그 gateway는 별도 Basic 인증을 요구한다. live 브라우저 context에
  해당 공개 origin으로 범위를 제한한 `httpCredentials`를 비공개 설정으로 주입한다.
  인증값·JSON reporter의 설정·브라우저 cache는 커밋하지 않는다. 사용자 작업 이력의
  재시작 검증에는 목록에 표시되는 작업 유형과 외부 provider 호출 없는 입력을 사용한다.
- 공개/LAN 로그인 POST와 Set-Cookie, 실제 summary, 로그아웃 후 401 및 틀린 자격 401을
  확인했다. N150 Linux Chromium에서 데스크톱·모바일·UI 재시작 3건을 통과했다.
  실제 native/API 확인 이후의 degraded/401 응답 주입은 브라우저 장애 표시 검증으로 구분했다.
- 외부 provider 호출 없는 seed의 native/domain 성공·실패가 일치했다. UI 재시작은 새 lineage로
  동일한 잘못된 입력을 다시 실패 처리하며 retry는 0을 유지했다. 같은 batch lane의 후속 빈 결과
  작업은 성공했다. 종료 확인 시 pending/running은 0이고, 테스트 실패 attention만 확인 처리했다.
- 세 sensor의 반복 tick, code server·공유 plane health, UID10001·2GiB cgroup 및 API/MCP의
  Dagster SDK 부재를 확인했다. 다른 다섯 앱의 기존 컨테이너와 health는 유지됐다.

실제 운영 worker 강제 종료·timeout·cancel drill과 Whisper 모델별 최대 RSS·유료 provider 평가는
이번 운영 검증에서 실행하지 않았다. 해당 장애 회귀는 앞선 격리 검증 결과와 구분한다.
운영 접속·백업 receipt·초기 실패 및 최종 live 결과는 비공개 런북과 별도 실행 기록에 보존한다.
