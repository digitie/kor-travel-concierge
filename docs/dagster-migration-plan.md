# Concierge 공용 Dagster 이관 설계

작성일: 2026-10-06. 기준: Concierge `c10c443ecf19a62224413c48d3783b69ae987e4c`,
공통 Python `efcd671207d7f9e2fb01251bab6854a8d543279a`.
사용자 요청에 따라 설계를 먼저 정리하고 구현·회귀 검증을 진행한다.

## 목적과 책임

Map·PinVi·Geo와 같은 공용 Dagster daemon·webserver·PostgreSQL storage를 사용하고,
Concierge는 별도 gRPC code location `ktc.dagster.definitions`만 제공한다.
공용 제어 프로세스는 Concierge의 ETL·Whisper 코드를 import하지 않는다.
공통 `RecoveryPolicy`, 활성 실행 판정, bounded HTTP, child gRPC health, 운영 UI를 재사용한다.
실제 shared instance·workspace 등록은 Manager 정본에서 수행해야 하며, 앱 YAML을
작성한 것을 공용 daemon 설정 활성화로 집계하지 않는다.

`crawl_runs`는 요청·payload·lane·재시도 예산·heartbeat·사용자 중지·감사·결과의 정본이다.
Dagster는 실행 생명주기와 격리를 소유한다. YouTube·LLM·RustFS·검수 정책과 feature
공급 계약은 변경하지 않는다. 원본 미디어는 계속 무기한 보존한다.

## 실행과 발화

- 대화형·배치 job을 분리하고 각 Dagster run은 정확한 `crawl_runs.id` 한 건만 실행한다.
- API/MCP는 기존과 같이 pending 행을 만든다. sensor는 pending ID만 제한된 조회로 읽고
  실행 요청을 만든다. 빈 큐에서는 worker를 기동하지 않는다.
- worker의 원자적 claim은 ID·lane·pending·중지 여부를 확인하고 Dagster run ID를 같은
  transaction에 저장한다. 기존 retry generation·실행 advisory lock·분석 claim token을 보존한다.
- 센서는 소유 project/location/job의 활성 실행을 확인한다. 결정적인 run key는
  행 ID·도메인 retry generation·직전 Dagster 종료 실행 ID를 결합한다. claim 전에
  launcher가 실패해도 같은 run key 때문에 영구 중지되지 않고, 미제출 요청 재평가는 중복되지 않는다.
- 기존 source scan과 feature export 안전망의 enabled·interval 설정을 유지한다.
  센서는 가벼운 발화 판정만 하고 도메인 DB 쓰기는 격리된 job에 둔다.
- 수집은 과금·비멱등 구간이 있으므로 native 전체 job retry/resume는 기본 0회다.
  DB 일시 오류와 stale 복구는 기존 도메인 최대 3회 예산을 사용한다. provider 오류와
  예산 소진은 실패로 표시하고 명시적 재시작 API를 유지한다.

## 정지·소유권·복구

nullable `orchestrator_run_id`, `orchestrator_attempt` 정수와 조회 index를 추가하는 Alembic migration을 코드보다 먼저 적용한다.
legacy heartbeat 회수는 이 필드가 없는 행만 담당한다. Dagster 소유 행은 metadata를 DB
transaction 밖에서 확인하고, bounded keyset page/cursor를 이어 읽는 전용 회수 경로를 사용한다.

생존 실행·metadata 조회 오류는 사망으로 처리하지 않는다. terminal 실행, 충분한 grace가 지난
없는 metadata만 소유권·heartbeat·retry generation·실행 advisory lock을 다시 확인하고 회수한다.
cancel_requested 또는 명시적 Dagster 취소는 cancelled로 마감하며 자동 재실행하지 않는다.
정상 종료의 pending 인계는 아래 종료 상태표를 적용한다.
terminal SUCCESS인데 도메인 상태가 완료되지 않았으면 성공으로 위장하지 않는다.
회수 시 이전 분석 attempt의 lease도 함께 정리하고 늦은 결과의 fence를 보존한다.
정상 SIGTERM 정리는 기존 pending 복귀 정책을 유지하고, native monitoring은 강제 종료·시간 상한을 맡는다.

## 자원 제한

한 job의 step 동시성은 1개, lane별 활성 실행은 1개, project 실행 예산은 2개로 제한한다.
현재 프로세스 안에서만 동작하는 Whisper 1개·캡션 최대 3개 semaphore는 서로 다른 run
프로세스에서도 공유되는 Linux 잠금으로 보강한다. 취소·프로세스 종료 시 잠금이 반환되고,
자식 RSS·시간·8MiB 결과 상한과 프로세스 그룹 회수는 유지한다.
API와 code-server의 DB pool은 분리하고 worker pool/overflow·connection/statement/lock timeout을
제한한다. code-server cgroup은 2GiB·CPU 2개·종료 유예 180초를 기본으로 유지한다.
run 상한은 기본 6시간으로 명시하고 환경 설정으로 조정한다. 목표 처리 시간으로 표현하지 않는다.

## 운영 UI와 인증

기존 작업 화면과 domain 상태·중지·재시작 기능을 보존하면서 공용 Dagster 대시보드를 추가한다.
API GraphQL은 Concierge location만 조회하고 최신 종료 실행과 오래된 활성 실행을 함께 표시한다.
응답 4MiB/전체 10초 상한, tick 전체 상태 선택·최신 LIMIT, 오류 시 마지막 성공 snapshot 유지,
실제 job 상한·코드 위치·실행 상세를 반영한다. 인증·BFF actor·Origin 정책은 앱이 소유한다.
로그인·메뉴를 공용 component에 연결하되 기존 httpOnly session 및 admin secret 계약을 보존한다.

## 전환·롤백과 검증

1. 독립 두 렌즈 설계 리뷰와 finding 반영 뒤 구현한다.
2. 독립 PostGIS에서 schema upgrade/downgrade, claim 경합, alive/terminal/missing/조회 오류,
   첫 page 생존·다음 page 회수, 취소·재시도 예산·late write fence를 검증한다.
3. 실제 Dagster module autodiscovery·gRPC child health·resolved executor·native 실패/정지/복구를 검증한다.
4. 전체 backend 회귀, frontend lint/type-check/unit/build와 n150 live/Linux UI 검증을 수행한다.
5. 기존 APScheduler를 drain한 뒤 공용 workspace와 센서를 등록한다. 두 실행자를 동시에 켜지 않는다.
   설정·이미지·schema·source revision을 기록하고 기존 대기열·반복 주기·원본 미디어를 보존한다.
6. 롤백은 센서·code location 실행을 drain한 뒤 legacy backend를 선택하고 pending·running을
   확인한다. Dagster 소유 실행이 남은 상태에서 APScheduler를 켜지 않는다.

검증 전 항목은 NOT_RUN이다. 운영 배포·공유 worker 장애 주입·RSS 감소율 실측을
로컬·격리 환경 결과와 구분한다. 구현 중 확정된 계약 변경은 이 설계와 ADR에 반영한다.

공식 API 근거: [sensor run key·평가 주기](https://dagster.io/docs/guides/automate/sensors),
[RunRequest·sensor 계약](https://dagster.io/docs/api/dagster/schedules-sensors).
공통 채택 가이드는 [공통 저장소](https://github.com/digitie/kor-travel-common/blob/efcd671207d7f9e2fb01251bab6854a8d543279a/docs/runbooks/dagster-adoption.md)를 따른다.


## 설계 리뷰 반영: 실행 결과와 인계 계약

기존 worker가 예외를 흡수하므로 Dagster adapter는 실행 후 row를 다시 읽는다.
현재 owner의 DONE만 정상 성공이고 quota_deferred는 경고 결과로 남긴다. FAILED는
`Failure(allow_retries=False)`로 전달한다. DB 재투입 PENDING은 owner CAS로 native 연결을
해제하고 attempt를 올린 뒤 명시적 실패로 남긴다. claim no-op는 handler를 실행하지 않고
skip 결과로 남긴다. ownership_lost는 성공으로 위장하지 않는다. API 공급 계약은 바꾸지 않는다.

pending sensor는 project `concierge`·location `ktc.dagster.definitions`·repository
`__repository__`·job·crawl ID·retry generation·orchestrator attempt 태그를 사용한다.
해당 태그의 최신 run을 최대 4건만 조회해 직전 실행 ID를 결정한다. QUEUED·
STARTING·STARTED·CANCELING은 새 요청을 막는다. NOT_STARTED는 영구 차단하지 않는다.
dispatcher/sensor 태그와 원래 dagster/run_key·세대·row identity를 확인하고 동일 run_key의
RunRequest를 반환해 기존 run을 재제출한다. Dagster 1.13.24의 sensor daemon은 기존
NOT_STARTED run을 새로 생성하지 않고 submit_run으로 인계한다. UNKNOWN은 재제출하지 않는다.
새 run 생성 예산 4개와 같은 run의 미제출 인계를 구분한다. 이 인계는 claim/외부 provider를
실행하지 않았으므로 과금 재실행으로 집계하지 않는다. backend 재기동 뒤 동일 key 재제출
native 경로를 회귀한다. metadata 오류·잘못된 origin은 UNKNOWN이며
key를 회전시키지 않는다. 같은 attempt의 claim 전 terminal 4건이면 pending row를
generation/owner CAS와 advisory lock으로 failed+attention=open으로 종결한다. 자동 발화는
최초 1회+재발화 3회다. 센서가 yield 전 죽으면 같은 key로 재평가하고, 제출 후 claim 전
죽으면 metadata predecessor로 재구성한다. pending 조회도 lane별 ID keyset/cursor를
진행하므로 첫 페이지의 unresolved 행이 뒤의 요청을 영구 차단하지 않는다.

| 종료 의도/결과 | 도메인 상태 | 이전 native 연결과 예산 |
| --- | --- | --- |
| domain 사용자 중지 또는 native CANCELING/CANCELED | cancelled | 자동 재개 없음 |
| 운영 SIGTERM/SIGINT, native STARTED가 확인됨 | pending | owner CAS로 연결 해제, attempt 증가; domain retry_count 보존 |
| 신호 수신 뒤 metadata UNKNOWN | 현재 owner 연결 유지 | 확인 전 재개 없음; 이후 명시 취소는 cancelled |
| worker hard-crash, terminal FAILURE, stale lease | pending 또는 예산 소진 failed | 실행 advisory lock 확인, retry_count 증가, attempt 증가 |
| native SUCCESS인데 domain running | failed+attention=open | 부작용 재실행 대신 운영 확인 |
| DB 재투입 | pending | 기존 retry_count 예산, owner 연결 해제·attempt 증가 |

worker signal adapter는 기존 handler/watcher와 자식 cleanup을 await한 뒤 인계한다.
정상 종료 시 분석 lease를 먼저 초기화하고, 정상 인계 이후의 옛 CANCELED receipt는
새 attempt를 종결하지 못한다. 기존 row/retry fence에 native owner ID를 추가한다.
유효한 native run이 살아 있는 오래된 heartbeat는 재큐잉하지 않는다. native monitoring의
시간 상한 취소는 사용자에게 cancelled로 보이며 기존 명시적 재시작 기능을 사용한다.

## 설계 리뷰 반영: 실행 방식 전환 fence

singleton `scheduler_control`에는 backend(`legacy`/`dagster`)와 전환 generation을 저장한다.
migration의 초기값은 legacy다. 새 바이너리가 배포됐다는 이유로 실행 방식을 바꾸지 않는다.
모든 legacy claim/maintenance와 Dagster claim/maintenance는 같은 admission shared advisory
transaction lock 아래 backend를 검사한다. Dagster 요청은 control generation도 검사한다.
전환 CLI는 expected-generation을 필수 입력받고 exclusive admission lock 아래 active domain
작업이 없는지 재확인한 뒤 generation을 증가시킨다. native metadata 확인은 그 transaction
밖에서 수행하고, metadata UNKNOWN 또는 소유 location 활성 실행이 있으면 전환을 거부한다.
옛 세대 queued request는 새 세대 claim에서 거절된다. rollback은 모든 owned pending의
native terminal 확인 뒤 연결을 해제하고 attempt를 증가시킨다. active/running은 강제 인계하지 않는다.
기존 fence 없는 APScheduler 이미지가 남아 있으면 먼저 stop/drain해야 한다. 새 Manager target은
공용 code-server만 기본 기동하고 APScheduler는 명시적 legacy profile에서만 선택한다.

## 설계 리뷰 반영: Whisper 부모 강제 종료

프로세스 간 슬롯은 kernel flock이며 부모만 소유하지 않는다. 경로는 code-server 컨테이너의
동일 UID 전용 디렉터리다. O_NOFOLLOW·owner/mode 검증으로 lock 파일을 열고, 대기 중 취소 가능하다.
명시적 LOCK_UN 대신 close만 사용한다. 같은 open file description의 FD를 작은 stdlib supervisor와
provider에 pass_fds로 상속해 부모만 죽어도 새 Whisper가 슬롯을 가져가지 못하게 한다.

supervisor는 별도 session의 leader이고 provider/FFmpeg는 그 process group에서 실행한다.
run worker는 watchdog pipe의 유일한 write FD를 보유한다. parent SIGKILL/OOM으로 EOF가 오면
supervisor가 해당 group을 회수한다. RSS·시간 상한은 supervisor도 감시한다. provider 종료,
parent EOF 또는 정상 중지 뒤 손자를 포함한 group을 SIGKILL하고 슬롯은 마지막 상속 FD가
닫힐 때 반환한다. 이 계약은 DefaultRunLauncher가 code-server 안에 run worker를 만드는
실제 shared profile에 한정한다. 컨테이너별로 별도 /tmp를 갖는 DockerRunLauncher로 바꾸려면
공유 lock mount와 별도 승인된 격리 검증이 먼저 필요하며 현재 구성에서는 사용하지 않는다.
최소 pool 4/overflow 0으로 execution lock·handler·watcher 수요를 수용하고 connect 5초,
statement 30초, lock 2초 상한을 적용한다. 기존 cgroup high-water admission도 보존한다.

## 설계 리뷰 반영: shared profile·UI acceptance

Manager `config/docker-targets.yml`의 conc target을 shared로 선언하고, code-server command
`-m ktc.dagster.definitions -p 12603`에서 workspace를 유도한다. shared instance의
dagster/code_location 상한 2, concierge JOB_TAG 각 job 1, monitoring/resume=0을 실제
정본에 결박한다. Dagster family는 Map/PinVi/Geo와 동일한 1.13.24/postgres 0.29.24다.
Gemini 호환 protobuf 계열은 별도 dependency resolution과 실제 positive/negative gRPC health로 검증한다.
API/MCP image에는 Dagster dependency를 설치하지 않고 API는 공용 bounded HTTP만 import한다.

summary는 예상 repository+location이 정확히 1개인 경우만 ok다. GraphQL HTTP 200의
PythonError/누락 location도 degraded다. runs는 해당 code_location 범위의 최신 terminal과
오래된 active를 합치되 ID 중복을 제거한다. tick statuses 넷과 native LIMIT을 명시한다.
공용 UI는 fetching 중/첫 실패/정상/정상 후 degraded를 구분하고 정상 snapshot을 유지한다.
last-good는 브라우저 인증 세션 내 메모리에만 보관하고 logout/unmount에서 버린다.
선택한 실행 ID 상세는 현재 snapshot과 결박하며 실행 상한은 실제 run tag만 사용한다.
공용 LoginForm/AppMenu로 교체하되 기존 session·Origin·rate-limit·actor 정책을 그대로 검증한다.
기존 작업의 domain 상세·중지·재시작·attention과 신규 운영 화면은 함께 접근 가능해야 한다.

필수 acceptance 추가: 연속 pre-claim 실패 4회, NOT_STARTED crash window, pending 첫 page
UNKNOWN과 다음 page 발화, provider 실패의 native FAILURE/추가 native retry 0, 정상 SIGTERM과
native cancel의 차이, 부모 SIGKILL 뒤 child/손자 회수와 글로벌 Whisper 동시성 1,
dual-mode claim·generation stale 요청 거부, maintenance enabled/주기/첫 발화,
actual launcher/cgroup/queue budget, HTTP200degraded/인증 만료/선택 상세/mobile overflow.
LLM 과금의 exactly-once나 운영 RSS 감소율을 이 설계만으로 보장하지 않는다.


## 설계 3판: 합산 메모리 예약과 supervisor 자체 종료

2GiB code-server에서 provider 자식의 **예약 합계는 1024MiB**, 나머지 1024MiB는
code-server·두 run/step worker·supervisor·DB·기타 메모리 headroom이다. 256MiB 단위 네
슬롯을 하나의 짧은 flock admission gate 안에서 원자적으로 확보한다. Whisper는 설정된
메모리 한도를 올림해 예약하고 기본 1024MiB이므로 네 슬롯 전부를 차지한다. 캡션은 한
슬롯과 provider 동시성 슬롯을 함께 얻으므로 Whisper와 세 캡션이 동시에 모델을 올릴 수 없다.
1024MiB 초과 Whisper 설정은 이 profile에서 fail-closed한다. 슬롯 부족 시 부분 잠금을 모두
반환하고 취소 가능한 대기로 돌아가며, 대기에도 120초 상한을 둔다. 획득 FD는 supervisor와
provider에 함께 상속하고 LOCK_UN하지 않아 부모만 죽어도 예약 합계가 지켜진다.
현재 cgroup 사용량이 1536MiB 이상이면 별도로 신규 claim도 보류한다. 예약은 RSS 감소율이나
모든 ETL 메모리의 상한 보장이 아니며 실제 다중 실행 headroom/RSS 검증은 별도다.

provider 시작 bootstrap은 heavy import 전에 Linux PR_SET_PDEATHSIG(SIGTERM)와 handler를
설치하고 supervisor parent PID를 전후 확인한다. supervisor가 SIGKILL/OOM되면 provider의
handler가 현재 소유 process group 전체를 SIGKILL한다. run worker가 살아 있으면 기존
_stop_group도 이를 독립적으로 회수한다. supervisor는 provider exit/OOM을 감시해 group을
회수한다. fork~bootstrap 사이에도 provider가 heavy 작업 전에 사라진 부모를 확인한다.
supervisor는 자기 group을 회수하므로 외부 PID를 탐색해 kill하지 않는다. parent의 회수는
원래 child가 살아 있는 동안만 동일 group identity를 사용하고, 종료한 group의 후속 회수는
supervisor가 맡는다. 여러 보호자와 provider를 동시에 SIGKILL하는 임의 장애의 완전 회수를
보장한다고 표현하지 않는다. container restart는 해당 PID namespace 전체를 정리한다.
독립 hard-kill 회귀는 run worker와 supervisor를 각각 종료해 child/손자·슬롯·다른 정상
group 생존을 확인하며, 예약 4단위+캡션/Whisper 상호 배제도 실제 다중 프로세스로 검증한다.

### 구현 시 공유 배포 계약 확인

Manager의 code location은 재로딩 가능한 `dagster code-server start` proxy와 기존 child health/reaper probe를 사용한다. proxy heartbeat TTL은 600초다. 전체 container 재시작으로 native 실행 추적이 유실되는 경우에는 Manager의 기존 location·incarnation 한정 reaper를 재사용하며, 건강 검사의 Docker unhealthy 표시만으로 재시작된다고 가정하지 않는다.

### supervisor hard kill 보강

provider가 장시간 C 함수 안에 있으면 Python SIGTERM handler가 지연되는 실제 반례를 반영했다. stdlib guardian은 `ktc.process_guard`로 옮겨 ETL package의 eager import를 피한다. guardian fork 직후 provider에 kernel PDEATHSIG(SIGKILL)을 설치하고, 같은 process group의 독립 stdlib watchdog이 guardian 전용 pipe EOF를 감지해 손자까지 SIGKILL한다. watchdog 자신이 group identity를 고정한다. 정상 종료는 guardian이 소유 멤버를 먼저 회수하고 watchdog을 wait한다.


### 실제 timeout과 Python 런타임 보정

Dagster 1.13.24 monitor는 runtime 초과 때 CANCELING 뒤 FAILURE를 기록한다.
native worker의 외부 취소는 먼저 pending으로 바꾸지 않고 owner lease를 보존한다.
실제 start_time과 native max_runtime로 시간 초과를 판별해 recovery의 최대 3회 예산을 적용한다.
정상 종료는 분석 lease reset·owner release·attempt 증가·pending 전이를 같은 transaction에서 수행한다.
manylinux Python의 os.pidfd_open 부재는 libc의 pidfd_open/pidfd_send_signal로 보완한다.
최종 전환·rollback·검증 절차는 [적용 가이드](dagster-adoption.md)를 따른다.

metadata UNKNOWN의 lane 격리를 위해 dispatch cursor는 tick마다 시작 lane을 교대로 선택한다.
25초 전역 예산을 한 lane이 소진해도 다음 tick에서 다른 lane을 먼저 조회하고 각 keyset cursor를 보존한다.
