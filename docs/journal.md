# JOURNAL — 작업 일지

## 2026-10-19 — T-201 현재 계약 정산

- #259 근거로 구현·격리 수용과 운영 changed-token/자동 실행을 분리했다.
- ADR-49/50과 공급 API·아키텍처·다음 작업 포인터를 현재 구현에 맞췄다.
- Manager lane은 최신 정본과 실제 CS/webserver 동일 config에서 limit1을 확인했다. 실제 연결 단절은 후속 #261의 직접 보강 함수 범위이며 운영 전원 차단과 구분한다.


## 2026-10-19 — 변경 token·부분 실패·중단 재개 격리 통합

- 실제 Geo fixture/Concierge loopback HTTP와 PostGIS 회귀 47 PASS, Map main e46c223의 실제 adapter/저장 경로 3 PASS를 확인했다.
- 부분 503 및 취소 중 cursor 미전진, 성공한 장소만 중간 export, 복구 후 정상 대상 HTTP 재호출/Map row_revision 추가 변경 없음, 재생 중복 없음까지 검증했다.
- 제품 파일과 운영 데이터/컨테이너를 바꾸지 않았다. 새 n150 live UI91 PASS 및 post-runtime fence PASS를 확인했다. 두 독립 리뷰 OPEN 0이며 운영 changed-token/daemon 수용과 구분한다. 상세는 [수용 문서](geo-changed-token-acceptance.md)에 남겼다.


## 2026-10-18 — 운영 전환과 자막 탭 E2E 선택자 보강

- API·MCP·코드 서버·UI 네 runtime 전환 후 소스/이미지/환경 보존과 최종 정상 기동을 확인했다. 최초 기준선과 동일 데이터 후속 실행은 모두 장소 변경 0건이었다.
- 실제 PostgreSQL 회귀 37건, SQLite 기준선 15건, 실제 PostgreSQL 동시성 2건을 통과했다. 두 독립 제품 리뷰의 지적은 해소했다.
- 최종 UI 검증 소스는 5836c1e7이며 결과 보고서 SHA-256은 96655e5dcf9557429d6d03af823ba04eeaeac45d3917f74155dc3dd60d2df346이다. 실제 로그인·지도·장소/검수 UI와 브라우저 장애 주입을 포함한다. 업무 데이터 쓰기는 실행하지 않았다.
- 자동 daemon 실행, 실제 변경 데이터의 전량 재해결, 실수집 CPU/RSS 비교는 이번 통과 범위에 포함하지 않는다. GitHub checks가 없어 CI 성공으로 표기하지 않는다.

- 네 runtime 교체와 최초 기준선·동일 데이터 재실행 검증을 완료했다. 자동 daemon은 중지 상태를 유지한다.
- n150 공개 UI 첫 실행은 81/91이었다. 테스트 브라우저의 WebGL2 비활성화를 재현했고, 브라우저 옵션만 보정한 다음 지도 관련 10개는 통과했다.
- 두 번째 실행은 90/91이었다. 자막 탭 전환 애니메이션 중 두 tabpanel이 잠시 함께 남아 이름 없는 선택자가 strict 오류를 일으켰다. 활성 탭의 aria-selected와 정확한 패널 이름을 확인하도록 좁게 보강했다.
- 원문 타임스탬프·정리 문장·타임스탬프 제거·빈 자막 검증은 유지한다. 제품 frontend/backend bytes는 바뀌지 않았다. 최종 공개 UI 91/91 PASS(재시도·생략 0)를 확인했다.


최근 두 달의 작업 진행 역사를 역시간순으로 기록한다.

## 과거 기록 아카이브

| 파일 | 기간 | 항목 수 | 크기(bytes) |
| --- | --- | --- | --- |
| [journal-2026-08.md](archive/journal-2026-08.md) | 2026-08-11 ~ 2026-08-31 | 4 | 10654 |
| [journal-2026-07.md](archive/journal-2026-07.md) | 2026-07-01 ~ 2026-07-24 | 46 | 125450 |
| [journal-2026-06a.md](archive/journal-2026-06a.md) | 2026-06-05 ~ 2026-06-29 | 129 | 199684 |
| [journal-2026-06b.md](archive/journal-2026-06b.md) | 2026-06-03 ~ 2026-06-05 | 20 | 34751 |

과거 기록 검색: `rg <패턴> docs/archive/`. 아카이브의 새 분리는 항목 경계·220 KiB 제한과 링크 도달을 확인한다.

---

## 2026-10-17 — T-200 첫 Geo 토큰 기준선 정합

- 별도 ext4 feature 작업 트리와 초안 PR #258에서 첫 관측 token+baseline marker를 같은
  transaction의 insert-only claim으로 저장했다. 동일 token의 후속 tick도 장소 재해결·dirty를
  만들지 않으며 기존 CURSOR-only+stale·중단 재개·오류 prefix·좌표 fence는 유지한다.
- 원본 main에서 새 첫 관측 회귀의 장소 재해결 도달 실패를 재현했다. 수정 후 소유 in-memory
  SQLite SQL 원자성/충돌/두 번째 쓰기 실패 등 15건 통과, PG DSN 없는 backend 전체
  434 PASS/612 SKIP다. 최초 scheduler import 경로 누락 collection error는 보존했다.
- 변경 Python Ruff와 frontend type-check·376 tests·lint·production build는 통과했다.
  전체 Ruff는 main 기존 286건 대비 282건으로 실패/신규 0건이며 다른 파일을 수정하지 않았다.
  실제 PostGIS 회귀·두 독립 리뷰·운영 token/첫 run/배포 검증은 별도 미완료다.
  기존 T-199/T-200/T-201 운영 수용 조건을 소급 완료하지 않는다.

## 2026-10-14 — T-199 단독 backend/schema 소유 복구와 운영 UI 검증

- T-199 source0dd의 immutable API/MCP/CS runtime 세 개와 nullable0031을 적용했고 운영 토큰 컬럼/부분 인덱스·장소1233·dagster generation1·원3센서 exact origin/status 복원을 확인했다. 최신 인증 UI와 공유 PG/Dagster webserver/daemon은 유지했다.
- root 운영 helper의 상대 migration 경로 오류, 정상 종료 utility의 caller TimeoutError와 원 영수증을 보존하고 경로/응답 대기·소유 정리를 보강했다. 두 독립 적대 리뷰에서 Mounts 순서 오탐과 CLI PID중복 반례를 닫은 최종 제어기를 고정했다. 원 tag UNKNOWN 및 R6/R7 실패를 소급 완료로 바꾸지 않는다.
- 동일 backend tree의 PostGIS996 PASS·실제 내부/외부 auth/replay401·새 backend에 연결한 운영 UI91 PASS(skip/retry/flaky0)와 전후 source/runtime fence를 확인했다. Geo provider 성공·T-200 첫 refresh·T-202b URL 및 전체 track 완료는 별도이며 Odroid 세 저장소의 live NOT_RUN 예외 병합과 분리한다.

## 2026-10-14 — T-206 번들 간 로그아웃 폐기와 상태 I/O 입장 상한

- 실제 최신 공개 UI90과 별개로 원 cookie를 직접 재사용하면 LAN/public 보호 API가 200임을 발견했다. 독립 모듈에서 RED 1을 재현했고 private 파일 nonce·marker로 공유하도록 수정했다.
- 최초 적대 리뷰 2인이 timeout 이후 원 I/O 200개 누적 반례를 확인했다. 초기 BLOCK 원문을 보존하고 먼저 thunk admission8개·실제 settle 전 슬롯 유지·streaming expiry cleanup을 적용했으며 R5에서 유한 상한32개로 조정했다. 100+100 요청에서 작업 32개 상한과 I/O 회복 뒤 정상 인증을 검증했다.
- 최신 frontend 376 PASS·lint/type/build PASS·실제 production compiled Proxy/Route Handler HTTP 12 PASS다. backend는 소유 fixture이며 운영 API/provider 성공으로 확대하지 않는다. PR #256에서 독립 source/controller 리뷰2인의 발견을 수정했고 새 immutable UI에 반영했다. 운영 LAN/public 원cookie replay401·artifact/source/public asset hash·전체 공개 UI91 PASS를 확인했다. R4의90PASS/1FAIL과 원 태그 UNKNOWN은 별도 보존하며 backend/provider 전환은 미완료다.

## 2026-10-14 — T-205 인증 감사 요청의 정지 격리

- 최종 제품 소스 `4e3899da`의 frontend 전체 358 PASS·lint/type PASS와 동일 소스 production build를 확인했다. 독립 적대 리뷰 2인의 최신 전체 source 판정은 PASS/OPEN 0이며 최초 정지 취소 반례의 BLOCK 원문은 보존했다.
- n150 Chromium에서 새 인증 소스와 격리 실제 API/native를 연결해 감사 HTTP 지연 중 로그인·거절·로그아웃 3 PASS, 정상 복구 후 실패·취소·성공 native 실행/로그 popup·재조회·로그아웃을 390/1024/1440px에서 9 PASS했다. 두 실행 모두 skip/retry/flaky 0이다. 최초 3건 실행의 1개 실패는 Next route announcer와 로그인 오류를 같은 alert로 고른 하니스 모호성으로 보존하고 정확한 로그인 오류 슬롯을 지정했다. 운영 Geo provider 성공으로 확대하지 않는다.
- 기존 운영 이미지의 공개 사이트는 n150에서 인증·Dagster 5건 PASS, 지도 4건은 실제 WebGL2 미지원으로 FAIL이었다. software WebGL 실행 옵션도 지원되지 않아 WSL Linux Chromium으로 대체했고 실제 VWorld 타일·canvas·마커·장소 선택과 화면 크기별 Dagster 데이터 표시까지 기다리는 9건을 62.95초에 모두 통과했다(skip/retry/flaky 0). 초기 실패와 데이터 표시 이전 스크린샷은 별도 보존한다. 이 운영 기준선은 새 인증 이미지의 배포 성공 증거가 아니다.
- 기존 API·MCP 접수는 복원됐고 운영 내부·외부 로그인 POST 200/쿠키 발급을 확인했다. 기존 1,233건·schema 0030과 원래 앱 이미지를 유지했고 접수 복원 과정에서 센서 상태를 변경하지 않았다. 공용 배포 잠금이 사용 중이므로 새 이미지/schema 전환은 진행하지 않았으며 T-199/T-200/T-202b와 T-205 운영 반영은 미완료다. 다른 작업의 최소 배포 완료 뒤 현재 설정·백업을 새로 고정해 인수한다.
- 독립 리뷰 B가 본문 취소의 Promise가 끝나지 않는 실제 ReadableStream 반례를 재현했다. 요청부터 본문 취소까지 명시적인 deadline과 함께 기다리도록 수정하고 중단을 무시하는 fetch·cancel 회귀를 추가했다. 집중 11 PASS이며 최초 source 리뷰의 미해결 원문을 보존한다. 기존 정상 HTTP 성공을 정지 구현의 성공으로 확대하지 않는다.
- 실제 로그인·로그아웃 Route Handler가 감사 저장 요청을 무기한 기다리는 경로를 재현했다. 기존 구현에 새 회귀를 적용하면 8건 중 7건이 실패하고, 감사 fetch를 2초 뒤 중단하는 수정 후 인증 결과·쿠키 보존 8건이 통과했다. 감사 성공 여부가 인증 허용 판단을 바꾸지는 않는다.
- 실제 loopback HTTP 서버에서 헤더 무응답 요청의 중단, 끝나지 않는 응답 본문의 취소와 해당 요청 socket 회수, 다음 정상 감사 요청을 확인했다. HTTP client가 만든 유휴 연결까지 누수로 분류한 초기 테스트 실패는 보존하고 요청 socket 자체를 추적하도록 수정했다.
- frontend 전체 356 PASS, lint·타입 검사·production build PASS. 두 적대 리뷰와 n150 실제 UI 검증은 진행 중이며 운영 로그인 중단 원인을 모두 이 경로로 단정하지 않는다. 운영 전환 중 외부 PostgreSQL 재생성과 Manager 설정 변경이 감지되어 이미지·schema 전환을 중단했고, 기존 API·MCP 접수 복원을 먼저 수행한다.

## 2026-10-14 — T-202a/T-203 연결 실패 계약 검증

- T-199에서 이미 구현한 connect 2초·read/write/pool 10초 timeout을 유지하고 일반 보강·격리 보강·refresh 기본 client 생성 경로의 ConnectTimeout 흡수를 검증했다. 실패 시 기존 행정코드·토큰은 보존되고 일반 호출 session도 정상 commit할 수 있다. 실제 PostGIS 집중 8 PASS와 변경 테스트 Ruff를 확인했다. 이는 timeout 설정 기제 검증이며 실제 SYN 무응답 효과를 측정했다고 주장하지 않는다.
- 설정 예시에 계획 URL placeholder를 명시했다. Settings 기본값·앱·frontend 구현은 불변이며 T-202b 운영 URL 전환과 장애 drill은 미완료다. 고정 테스트 구현의 두 source 적대 리뷰가 PASS/OPEN 0이며 n150 native Chromium UI 9 PASS(71.58초, skip/retry/flaky 0)를 재확인했다. UI는 변경 없는 T-200 제품 runtime을 사용했고 fixture Geo 기반이며 운영 Geo 통합·호스트 전환 효과를 증명하지 않는다. 최종 문서 리뷰에서 발견한 ADR-50의 기존 운영 주소 4곳도 역할·포트를 보존한 placeholder로 정정했다. TEST-NET 효과 시험 주소는 유지했다.

## 2026-10-14 — T-204 일지 아카이브 분리

- 최근 두 달을 현재 일지에 남기고 이전 기록을 월별 아카이브로 분리했다. 220 KiB를 넘는 달은 날짜 항목 경계로 나눴다. 인덱스에 기간·항목 수·파일 크기를 기록한다.
- 기존 날짜 항목의 누락·중복을 검사하고 원문과 대조했다. 이동으로 달라지는 상대 Markdown 링크는 기존 저장소 대상을 가리키도록 재기준화했다. 보안 규칙을 우선해 기존 공개 일지에 남아 있던 운영 호스트 주소 5곳과 공개 도메인 참조 3곳은 마스킹했으며, 공개 bind 기본값을 운영 도메인으로 잘못 분류한 초기 마스킹 2곳은 원문대로 복원했다. 백로그의 기존 운영 주소 6곳도 역할을 보존한 placeholder로 바꿨다. 파일 끝의 바깥 빈 줄 4곳도 정리했으며, 마스킹·링크 재기준화·파일 경계 공백 외의 항목 본문은 동일하다. 아카이브는 읽기 전용이며 새 기록은 현재 일지 상단에 추가한다.

## 2026-10-14 — T-200 최신 source·실제 native·UI 검증

- 고정 구현 `9b26e8e1`의 전체 backend 1023 PASS(669.01초), 집중 PostGIS 52 PASS와 두 독립 최신 FULL source 적대 리뷰 PASS/OPEN 0을 확인했다. 이전 오류 prefix·지속 신규 행 유입의 BLOCK 원문은 보존하며 durable checkpoint와 순회 상한으로 수정했다.
- 별도 PostGIS·실제 HTTP 서버·Dagster code-server/webserver/daemon/default launcher·multiprocess worker와 기동 API에서 10개 효과 검증을 통과했다. 50회 오류 후 native Failure/진행 위치 보존, 다른 maintenance job 성공, 재실행의 tail→prefix 복구, 동일 릴리스 무 reverse 호출, 정상 미해결의 옛 코드 보존, HTTP 대기 중 실제 취소/DB transaction 미점유, 순회 중 새 tail의 다음 run 복구, 최종 changes 피드 토큰 반영과 5개 job 요약을 확인했다. 유료 provider 발화는 비활성화했다.
- 이는 **운영 Geo provider 성공 시험이 아닌 격리 HTTP fixture 시험**이다. Geo 배포/backfill과 Map의 토큰 신뢰·hash 규칙 반영 뒤 수행할 통합 e2e·첫 운영 run은 남는다. Manager lane PR #473은 `021587e4`로 병합됐으나 운영 설정 반영은 아직 하지 않았다.
- n150 native Chromium UI 9 PASS(40.18초, skip/retry/flaky 0). 390/1024/1440px에서 실제 refresh Failure/Canceled/Success 실행 조회, 5개 job, runtime 상한, maintenance의 도메인 링크 부재, 실제 native 로그 popup, 재조회와 logout→401을 확인했다. frontend Git source는 기존 `0dd0e29e`와 동일하고 최신 API/native만 별도 DB로 구동했다. 최초 하니스는 테스트 패키지 경로 오류로 브라우저 실행 전에 실패했으며 경로를 보강해 다시 실행했다. 초기 실패도 보존한다.

## 2026-10-14 — T-200 순회 상한으로 지속 유입 중 재시도 보장

- `7b2eb8b9` 전체 backend 1018 PASS(699.43초) 뒤 독립 재리뷰는 기존 오류 prefix 복구를 확인했지만, 새 stale가 계속 추가되면 tail이 비지 않아 과거 오류를 wrap하지 못하는 반례를 재현했다. R2 BLOCK도 보존한다.
- 진행 checkpoint에 이번 순회의 최대 place ID를 함께 저장했다. 중단 후에도 같은 상한을 유지하고 유한 tail 뒤 앞 구간을 처리한다. 한 바퀴 완료 후에만 다음 run이 새 상한을 캡처한다. 새 token은 이전 위치/상한을 사용하지 않는다.
- 실제 PostGIS에서 오류 시도 후 중단·재개 중 계속 신규 행을 넣어도 과거 오류 행이 재해결되는 효과와, 남은 신규 행은 다음 순회에서 처리되는 것을 확인했다. 잘못된 상한 4종은 호출/완료 토큰 전진 없이 실패한다. 수정 집중 52 PASS(42.18초), 신규 파일 Ruff PASS다. 두 최신 FULL source 재리뷰·최신 전체·live는 진행 중이다.

## 2026-10-14 — T-200 오류 prefix 순회 복구 보강

- 후보 `a891d802`의 전체 backend 1014 PASS(664.76초) 뒤 두 독립 적대 리뷰가 slow-error prefix의 재개 starvation을 각각 축소 실행 예산으로 재현했다. 기존 완료 장소 제외만으로는 닫히지 않아 원본 BLOCK을 보존했다.
- token-scoped 내부 keyset checkpoint를 장소별 시도 뒤 저장하고 다음 run이 뒤 ID부터 이어가도록 했다. 한 바퀴 끝에서 앞 구간을 한 번만 wrap하며, 새 token에는 이전 cursor를 재사용하지 않는다. 전역 완료 token의 stale0 조건과 공개 settings allowlist는 유지한다.
- 오류율 문턱은 50시도부터 즉시 검사하되 failure에도 checkpoint를 보존한다. 중단한 오류 구간 뒤 정상 장소의 처리, 오류 문턱 중단 뒤 뒤 구간 진행, 새 epoch reset, 내부 진행 key public write 거부를 실제 PostGIS 회귀에 추가했다. 수정 집중 47 PASS(37.51초), 신규 파일 Ruff PASS이며 최신 전체/두 재리뷰/live gate는 진행 중이다.

## 2026-10-14 — T-200 재개·cursor·메타데이터 회귀

- 최초 focused 40건은 시험의 async generator/all 오용 2건과 서로 다른 job의 정당한 DB 연결을 refresh 연결 점유로 오인한 1건으로 실패했다. await list와 실제 runtime처럼 job별 engine을 사용해 연결 반환 단언을 유지하고 40 PASS를 확인했다.
- op 실패 카운터는 output buffer가 아닌 Dagster Failure metadata에 싣는다. 실제 in-process failure event·paid retry 없음과 새 job active/UNKNOWN 격리 검증을 추가했다. 새 active-run fixture의 필수 run_config 누락 1건도 기록하고 보강한다.
- 같은 global 토큰의 새 stale 장소, partial commit 뒤 재개, 오류 문턱 초과/미만, NULL 토큰, 좌표 fence, 123건 keyset·HTTP 중 refresh pool 점유 0, export 동시 실행/fixpoint, 공개 settings 내부 cursor 400을 실제 PostGIS에서 확인한다. 전체/두 리뷰/live/UI/운영 gate는 진행 중이다.

## 2026-10-14 — T-200 재해결 job 구현 착수

- T-199 고정 구현 위 별도 브랜치에서 maintenance job을 끝에 등록했다. backend/generation admission과 같은 job 활성 metadata gate, 공용 RecoveryPolicy runtime tag와 기존 cooperative 취소를 재사용한다.
- version 헤더 조회, ID keyset 50개, 단일 HTTP client/connection 재사용, 장소별 짧은 격리 세션 commit, 행별 stale 재검사와 내부 cursor upsert를 구현했다. global 토큰 동일이어도 새 stale 장소를 누락하지 않는다.
- 코드·회귀·두 적대 리뷰·live/UI는 검증 중이다. Manager lane 및 Geo·Map 선행 운영 gate를 충족하기 전 새 job을 운영 활성화하지 않는다.

## 2026-10-14 — T-199 구현 검증과 운영 선행 조건

- 구현 `0dd0e29e`의 전체 13경로를 독립 적대 리뷰 2인이 검토해 OPEN 0/PASS를 확인했다. R1/R2의 오류 응답·mixed epoch·미해결 provenance 지적과 초기 테스트 실패는 보존하고 수정 뒤 재검토했다.
- 실제 PostGIS migration `0030→0031→0030→0031`에서 행 보존·부분 인덱스·단일 head를 확인했다. 보강/공급 집중 90건 PASS 뒤 symmetric epoch delta는 HTTP 회귀 11건 PASS다. backend 전체 995 PASS는 이전 `d18c3343`에서의 결과이며 최신 SHA 전체 결과로 확대하지 않는다.
- 최신 구현의 실제 HTTP fixture·PostGIS·기동 API changes 피드 6개 케이스가 통과했다. 성공 token, 503/깨진 응답 무쓰기, unresolved 공급 NULL, 반복 무 dirty와 좌표 변경 fence를 확인했다. 이는 운영 Geo provider 성공 시험이 아니다.
- 기존 공용 Dagster tick SQL의 정렬 병목은 Manager PR #472로 보강하고 검토 함수를 운영에 적용했다. 그 뒤 후보 API summary ok 및 n150 native Chromium 전체 live UI 90 PASS(0 skip/0 retry/0 flaky)를 확인했다. 초기 fixture 키 누락 1 FAIL은 own DB seed 뒤 단독·전체 재검증에서 통과했으며 첫 실패도 보존한다.
- 운영 Geo의 공개 인증 확인용 전용 키로 dataset/version 200을 확인했지만 data_token은 미제공이고 reverse/radius는 504다. 신규 키는 운영 Concierge에 아직 적용하지 않았다. T-199 코드 병합/배포는 ADR-49의 병렬 허용 범위이며 T-200 활성화·native Geo force 성공·호스트 이전은 완료로 표시하지 않는다.

## 2026-10-13 — Track 1·2 순차 구현 착수

- Concierge → Weather → Transport 순서의 사용자 지시로 최신 원격 기준에서 착수했다. 첫 PR은 T-199의 토큰 컬럼·보강 로직이며 운영값 전환은 선행 배포와 효과 검증 뒤 수행한다.
- 구현 전 독립 적대 검토에서 동일 global 토큰의 새 stale 장소 누락과 unresolved 옛 코드의 최신 토큰 봉인 위험을 발견했다. refresh는 행별 stale 대상을 확인하고, export는 성공한 보강의 토큰만 제공하도록 계약·회귀를 함께 정정한다.
- 첫 격리 PostGIS 실행은 컨테이너 초기화 재시작 중 연결 reset 8건과 additive 응답 필드의 기존 exact-object 검증 1건으로 실패했다. 초기 실패를 기록하며 새 필드를 계약 기대값에 추가해 재실행한다.
- 정상 reverse·radius의 토큰 전달, 헤더 인증, 오류/미해결 분리, snapshot fence와 동일 transaction dirty를 구현했다. `dd1-` + 32자리 소문자 hex라는 Geo ADR-069 정본을 확인해 초기 잘못된 40자리 hex 검증을 정정했다. 두 HTTP 정상 응답의 토큰이 다르면 기록하지 않는다.
- 깨진 HTTP200의 nested collection은 정상 미해결로 봉인하지 않고 errored로 재시도 대상에 남긴다. unresolved는 옛 코드를 보존하지만 공급 토큰은 NULL이며 성공 source만 provenance 토큰을 제공한다.
- 두 golden 테스트의 상대 import 누락을 고쳤다. 현재 admin 보강·신규 토큰 집중 회귀 36건 통과; feature 공급 회귀·전체 검증·두 적대 리뷰·live 검증은 계속 진행 중이다. 초기 실패는 최종 성공으로 덮지 않는다.
- 리뷰 반례의 행정코드 bool/객체/잘못된 길이를 거부하고, 완성 코드 조회 횟수 0을 서비스 밖에서 확인하도록 회귀를 강화했다. dirty 쓰기는 기존 `export → place → audit` 잠금 순서를 유지한다.
- 집중 PostGIS 보강·토큰·feature 공급 회귀 90건 통과. 새 migration의 실제 upgrade/downgrade/upgrade와 기존 행 보존·nullable 토큰·부분 인덱스도 확인했다. 최초 migration 하니스 seed는 필수 기본값 누락과 존재하지 않는 timestamp 컬럼으로 실패해 fixture를 실제 이전 schema에 맞췄다(제품 migration 변경 없음). 전체·live/UI·두 리뷰 closure는 아직 진행 중이다.
- nullable 토큰 컬럼과 geocoded 장소 부분 인덱스를 추가했다. 테스트·독립 리뷰·live E2E·UI E2E는 진행 중이며 완료로 기록하지 않는다.

## 2026-10-13: geo odroid 재배치 대응 설계(ADR-50)

- 문서만 바꿨다(코드·`.env.example`·CHANGELOG·contracts 없음; 6파일 — `docs/decisions.md`·`docs/tasks.md`·`docs/architecture.md`·`docs/journal.md`·`CLAUDE.md`·`AGENTS.md`). `docs/decisions.md`에 ADR-50(proposed)을 추가하고 `docs/tasks.md`에 T-202a/T-202b/T-203(Track 2 설계 ID T-CNC-01/02)·T-204(journal 아카이브 분리)를 대기로 올렸으며, `docs/architecture.md` §4.5에 geo 호출 경로 표(코드·값의 자리·호스트 현재→계획·timeout·키 자리)를 두었다. 저장소에 geo 연동 전용 문서(`docs/kor-travel-map-integration.md`·`docs/integrations/`)가 없어 §4.5가 그 자리다. `CLAUDE.md` "현재 작업"에 병렬 가능 포인터(T-202a·T-203) 1줄을 더했고, `CLAUDE.md`·`AGENTS.md`의 낡은 ADR 범위 표기(ADR-1~35 / ADR-1~33)를 "마지막 `## ADR-NN` 헤더가 정본" 포인터로 바꿨다(범위 숫자 재기입 없음).
- 배경: Track 2(Manager ADR-58)가 geo·weather·transport를 n150에서 odroid(`<운영 호스트>`)로 옮긴다. concierge는 n150 잔류·REST만이며, 호스트 이동은 env `KOR_TRAVEL_GEO_V2_BASE_URL`(`config.py:268`) 하나의 변경이다(계획값 `http://<운영 호스트>:12501`, 포트 동일). 값의 자리는 n150 concierge 디렉터리(`${KOR_TRAVEL_CONCIERGE_REPO_DIR:-../kor-travel-concierge}`, git 저장소 아님) `.env` — Manager compose가 `env_file`로 전달한다(Manager `docker-compose.yml:1198·1262·1307·1355` @094d397; 렌더하지 않으므로 기대값만 문서화). 수신 service는 compose 정의상 넷이지만 scheduler는 `legacy-scheduler` profile(`:1287`, ADR-48 롤백 전용)이라 운영 재생성 대상은 api·mcp·dagster-code-server 셋이다(`conc` target `docker-targets.yml:491-502`). `env_file`은 생성 시에만 읽히므로 반영은 재생성이지 `restart`가 아니다 — 단 production Manager는 `ensure`를 거부하고(`compose_service.py:3621-3637`) 허용돼도 공용 PG까지 `--force-recreate`하므로, 명령은 Manager 정본(`compose-boundary activate-concierge --confirm`, `legacy_override_retirement.py:138-142·721-723` 또는 호스트 직접 `--no-deps --force-recreate`)에 위임하고 Manager ADR-58이 확정한다. 교차 저장소 번호(Track 2 설계에서 고정): Manager ADR-58·geo ADR-070·Map ADR-110·transport ADR-014.
- 결정 5개는 ADR-50이 정본이다: (1) REST만·배선 변경 0·재생성은 효과로 정의(명령은 Manager 정본), (2) 키는 DB `system_settings['kor_travel_geo_v2_api_key']` 우선(`settings_service.py:33,43-53`) — DB 값이 있으면 env 갱신은 효과가 없고, 운영 `POST /settings`는 비밀 키의 빈 값을 건너뛰어(`routes.py:3548-3550`) 행을 비울 수 없으므로 env 폴백 복귀는 DB 행 직접 삭제다; 정책 (가) VWorld 폴백 유지 vs (나) 발급 키는 geo §14-21과 하나로 결정, (가)의 전제(concierge 유효 키 == geo VWorld 기본 키)와 all-or-nothing 함정(geo `public_api_key.py:65` @6dd4951) 명시, (3) 전환은 Track 2 consumer URL 전환 단계(설계 §11.2 9단계; geo 플립·`mv_refresh` 다음 날)에서만 — 검사는 전파(세 컨테이너 `printenv` 전부 `.13` + 컨테이너 ID 변경; host network라 access log peer로는 컨테이너를 구분할 수 없다)와 효과(n150 geo-api stop 상태에서 api 발 1건 + code-server 발 1건, Dagster run 로그로 주체 식별, odroid access log peer `.14`·키 경로 200)로 나누고 + 잘못된 키 음성 프로브 4xx + 공용 PG·Dagster 컨테이너 ID 불변, (4) best-effort 불변 + connect timeout 분리 — 모듈 상수 `GEO_HTTP_TIMEOUT = httpx.Timeout(10.0, connect=2.0)`(T-203; `admin_region_service.py:90,254`), 검증은 클라이언트 생성 층의 기록용 더블로 고정(주입 경로 `:251-252`는 timeout 우회·MockTransport는 연결 단계 없음·비라우팅 주소는 환경 의존; isolated 경로는 HTTP 앞에서 place SELECT `:116-126`·`get_secret` `:138-140`을 하므로 장소 seed + monkeypatch 전제, 더블의 `ConnectTimeout`은 쓰기 세션 `:155` 전에 `:182-183`으로 흡수), 효과 층 시험(TEST-NET, `slow`·CI 제외)은 권장으로 병기, 회로차단은 두지 않음(지시문의 "후속 코드 T"는 PR 범위 규정이고 설계에 항목이 없다 — 소유자 결정 아님), (5) Track 1 상호작용 — odroid full load의 새 `data_token`이 ADR-49 refresh job(1 h maintenance job; Map의 ≤5분 센서와 다름)의 전 장소 재해결을 유발하며 수용을 기본으로(최종은 §14-19 소유자 결정; dump 복원이면 0).
- 발견: 운영 `KOR_TRAVEL_GEO_V2_BASE_URL` 실값은 미확인이다(설계 §2.2) — loopback이면 두 geo 호출은 신뢰 peer 면제로 통과해 키가 대조된 적이 없고(geo `public_api_key.py:55-56` @6dd4951) 전환 뒤 처음으로 키 경로를 탄다; 비어 있으면 호출 자체가 없어 전환 단계는 "최초 설정"이다. 현재 값 읽기를 T-202b 선행 확인에 넣었다. 피호출자 다운의 의미가 "즉시 RST"에서 "SYN timeout"으로 바뀌어 확정 1건당 최대 10 s 블록(within-radius는 reverse OK 뒤에만 호출, `:288-304`; 20 s는 connect 뒤 read 중 끊기는 중간 단절뿐)·ADR-49 refresh run 도중 geo를 잃으면 run 장기화가 생긴다(처음부터 다운이면 version 호출 1회로 종료; T-203이 호출당 2 s로 줄인다).
- odroid 상태(2026-10-13 03:4xZ 실측, 출처 Track 2 fact base): WSL 직접 ssh·NOPASSWD sudo·docker 그룹·NTP 수동 동기 완료; timesyncd 사이클 drop-in·compose v2/buildx·방화벽·fstab bind·swapfile 미완. geo는 아직 n150이다. "Track 2 설계 §n"은 Manager ADR-58(작성 예정; 설계 최종본 절 번호)의 해당 절이다 — ADR-50 "용어"가 정의하고 ADR-58 머지 뒤 T-202b (4)에서 재대조한다.
- 리뷰 반영은 세 회차였다(서수 대신 내용으로 적는다 — 하네스 보고의 "1차 리뷰"는 아래 B, "2차 리뷰"는 C다). **리뷰 A(초안, 2명)**: MED 5건 전부 반영(env_file 네 컨테이너·재생성, DB 행 삭제 경로, 20 s → 10 s, loopback은 추정으로, T-203 검증 기제 단일화), LOW 중 refresh job 서술·geo SHA·교차 번호 고정·회로차단 지시 차이·음성 프로브·dump 복원 전제·T-202 분리(a/b)·resume 포인터 반영.
- **리뷰 B(ensure 거부, 2명)**: HIGH 2건 — 운영 반영 기제로 적었던 Manager `ensure conc --recreate`가 production에서 거부되는 명령이고(`compose_service.py:3621-3637` @094d397; ADR이 인용한 `ktdctl-ui-migration.md:597` 행 자체가 "하드스톱" 명시) 허용돼도 `conc` target의 `services` 합집합(공용 PG·db-init·ui, `depends_on: [prom]` `:481` 폐포)을 `--force-recreate`한다는 지적을 전부 반영 — ADR 결정 1·3, T-202a 문안, T-202b, architecture §4.5, 이 항목에서 명령을 지우고 "runtime 세 컨테이너 재생성(`--no-deps`)" 효과로 바꾼 뒤 명령은 Manager 정본(`compose-boundary activate-concierge --confirm` = `backend/src/kor_travel_docker_manager/services/legacy_override_retirement.py:138-143·692-726`의 `--no-deps --force-recreate` api·mcp·code-server·ui, production lock 경로 `:401-402`·그 외 거부 `:417-419` / 호스트 직접)에 위임하고 Manager ADR-58 확정을 열린 결정·T-202b 선행 확인 (0)으로 올렸다; 수용 기준에 공용 PG·Dagster 컨테이너 ID 불변 검사 추가. MED — scheduler는 `legacy-scheduler` profile(`docker-compose.yml:1287`)이라 "네 컨테이너" 서술을 "compose 정의상 넷, 운영 재생성 대상 셋"으로 고치고 ADR 맥락에만 수를 적고 architecture 표·tasks는 포인터로; mcp 컨테이너(`mcp_server/tools.py:492·540·704·788`)를 검사에 추가. LOW 전부 반영 — `:252-253` → `:251-252`, 결정 5 단정 완화, "checkout" → "디렉터리", CLAUDE/AGENTS ADR 범위 표기 → 포인터, journal 크기는 T-204(아카이브 분리, XS)로 백로그 결박.
- **리뷰 C(T-203 전제·포인터, 2명)**: HIGH/MED 3건 — (1) T-203 수용 기준의 "별도 place/DB fixture 불필요·DB 단계 전 종료"가 isolated 경로 코드와 반대(HTTP 전에 place SELECT `:116-126`·`get_secret` `:138-140`·`_configured(api_key)` `:143-144`가 먼저라 seed + monkeypatch 없이는 더블이 호출조차 안 됨; isolated 예외 흡수는 `:256-257`이 아니라 `:182-183`) → T-203 (2)·ADR-50 결정 4·맥락·이 항목을 "장소 1건 seed + `get_secret` monkeypatch(기존 테스트 `:106-148` 패턴), 쓰기 세션 `:155` 전 종료"로 정정; (2) "Track 2 설계 §n"·"9단계" 포인터가 커밋되지 않은 scratchpad와 아직 없는 Manager ADR-58을 가리킴 → ADR-50 머리에 "용어" 줄(ADR-58 작성 예정의 해당 절, 머지 뒤 재대조)을 두고 "9단계"를 "consumer URL 전환 단계(§11.2 9단계)"로 내용 이름 + 괄호 번호로 바꿨으며 fact base 인용은 "(2026-10-13 실측, 출처 Track 2 fact base)"로 완결; (3) T-202b ①·②가 컨테이너별 효과를 access log peer로 확인하려 했으나 세 컨테이너 모두 `network_mode: host`라 peer가 전부 `.14` → 전파(`printenv` 전부 `.13` + 컨테이너 ID 변경)와 효과(api 발 1건 + code-server 발 1건, Dagster run 로그로 주체 식별, access log 기록)로 분리. LOW 전부 반영 — `activate-concierge`가 C6c projection 검증·lock·ui 재생성을 동반하는 이관 명령(`legacy_override_retirement.py:692-726`, `docker-management.md:490-493`)임을 열린 결정의 Manager 피드백에 추가; T-202b 의존 (5) Track 2 1단계(T-MGR-01b 간선 삭제) + Map T-MAP-01과 같은 창; T-204 크기 "432 KB" → `wc -c` 실측 바이트(HEAD 427,466 B; PR 시점 값은 T-204에)·기준 `wc -c` < 262,144 B; 회로차단은 열린 결정에서 제거(지시문은 범위 규정, 설계에 항목 없음); 방화벽 (가) 단정 → (가)/(나) 어느 안에서도 성립; 관계 절 ADR-49에 Track 1 상호작용 한 줄; scheduler "넷째" 조건을 DB backend 전환이 아니라 compose `legacy-scheduler` profile 기동에 결박; 라인 드리프트(`_configured` `:439-443`, `depends_on` `:481`, production `:401-402`/`:417-419`); 이 리뷰 회차 표기. 기각 0건.
- 미결(소유자, ADR-50 "열린 결정"과 1:1): 키 정책 (가)/(나), 운영 DB 키 행 유무·값(미확인; 비우려면 DB 직접 삭제), 전환 단계 재해결 수용 vs dump 복원, production 재생성 경로(activate-concierge vs 호스트 직접 — Manager ADR-58; 이관 명령 전제 피드백 포함), connect 2 s 승인 + 효과 층 시험 채택 여부. 설계와 달리 쓴 점: 백로그 ID는 저장소 규약 `T-NNN`(T-202a/b·T-203·T-204)으로 두고 설계 ID T-CNC-01/02는 별칭으로 병기; ADR 번호는 Track 1(ADR-49)이 먼저 머지돼 50이다; T-203 검증층은 설계 §12·§13의 "연결 거부 호스트에 2 s 안 False"(효과)가 아니라 클라이언트 생성 인자(기록용 더블)로 결박했고 효과 시험은 권장으로만 병기했다(이유: 주입 경로 우회·MockTransport 무연결·비라우팅 주소 환경 의존); 설계 §11.2의 "n150 `ensure map`"도 production `ensure` 거부와 충돌하므로 Manager ADR-58 작성자에게 피드백(ADR-50 결과와 한계); 회로차단은 지시문대로 코드 T를 만들지 않았고 ADR 기본도 "두지 않음"이라 소유자 결정 항목에 올리지 않았다; `CLAUDE.md`·`AGENTS.md`는 작업 범위 목록 밖 문서지만 금지 목록에 없어 포인터 줄만 손댔다.

## 2026-10-13: geo 데이터 토큰 재해결 설계

- 문서만 바꿨다(코드·마이그레이션·CHANGELOG 없음). `docs/decisions.md`에 ADR-49(proposed)를 추가하고 `docs/tasks.md`에 T-199/T-200-pre/T-200/T-201을 대기로 올렸다. `docs/feature-export-api.md`·`docs/architecture.md` §4.5/§6.4·`docs/themes-api.md`에는 "ADR-49 예정" 포인터만 두었고, resume 문서가 없어 `CLAUDE.md` "현재 작업" 최상단에 다음 작업 1줄을 두었다.
- 결정 6개(토큰 열 "마지막 시도" 의미·두 파싱 지점·헤더 인증·refresh job·dirty/payload 토큰·replay 가정 철회)는 ADR-49가 정본이다. 1차 리뷰 뒤 `unresolved` 기록은 `force=True` 경로 전용, 설정 토큰 전진은 대상 쿼리 0건일 때만, `_admin_snapshot` fence에 토큰 포함, `_merge_region` 토큰 불일치 시 None을 ADR 본문에 못박았다.
- 2차 리뷰 반영(HIGH 1·MED 6): (1) 1차에서 넣은 "`status != "OK"`는 errored" 규칙을 **전제 오류로 철회** — geo v2 reverse는 후보 0건을 `status: NOT_FOUND` + HTTP 200으로 돌려주고(geo `core/reverse_geocoder.py:73`) ERROR 바디는 항상 4xx/5xx라 concierge `raise_for_status()`(`:284`)가 먼저 잡는다; 그 규칙대로면 해상·섬 장소가 refresh 대상에 영원히 남아 설정 토큰이 전진하지 못한다. 경계는 "2xx면 unresolved, 예외·timeout이면 errored"로 되돌렸다. (2) within-radius fallback은 reverse `OK`+불완전 후보일 때만이고 `NOT_FOUND`는 fallback 없이 None(`:286-287`) — 추가 호출 여부는 열린 결정. (3) refresh 쓰기 경로를 bool 경로 배치 세션에서 **isolated 경로의 force 변형**(짧은 세션·FOR UPDATE·snapshot fence, 불일치는 `skipped`)으로 바꿨다 — HTTP 동안 transaction 보유와 `correct_place` 경주를 막는다. (4) T-199·T-200 코드 머지는 geo와 병렬 가능하고 선행은 배포 쪽(Map T-GR-03 → Manager lane → concierge T-200)임을 tasks 머리말·CLAUDE.md에 적었다. (5) `correct_place`의 토큰 NULL 되돌림은 `place_service.py` 수정이므로 T-199 수정 파일에 넣고 결정 2·6의 모순을 풀었다. (6) 설정 키 `kor_travel_geo_data_token`은 `ALLOWED_SETTING_KEYS`에 넣지 않고 job이 직접 upsert한다(운영 settings API 표면 비확대). (7) T-201 `rg … 0건` 범위를 현재 동작 서술 문서로 한정(journal·tasks 제외). LOW: 부분 인덱스 열 명시, `JOBS` 끝 append(`jobs=JOBS[2:]`)·Manager `code_location` 상한 2, reason 리터럴, `dagster-summary.openapi.json` 재생성 불필요 확정, unresolved 장소 옛 코드 유지 명시, 교차 저장소 인용을 origin/main 줄 번호로(Map `:567-575`, Manager 테스트 `:56-57`), `:3834-3840`·`:216-222`·`_payload_hash` 정정.
- 발견: 두 geo 호출처가 API 키를 `?key=` 쿼리로 보낸다(`admin_region_service.py:275, 322`) — refresh가 시간당 전 장소를 치면 로그에 키가 반복 남는다. `system_settings` 쓰기는 `ALLOWED_SETTING_KEYS` allowlist를 지난다(`settings_service.py:37-39`). 공용 Dagster의 `kortravelcommon/job` lane은 job 이름별이라 Manager에 1줄이 선행한다(lane 단언 테스트 `backend/tests/test_concierge_shared_dagster.py:56-57`, Manager origin/main @094d397).
- 철회: "MCP replay가 옛 행정코드를 복원한다"는 가정. replay는 receipt `response_json` 반환 경로이고(`place_service.py:3834-3840`) 행정코드 열을 되쓰지 않는다. T-199에서 `audit_logs.payload_json` 되쓰기 경로 부재를 grep으로 닫는다.
- 미결(소유자, ADR-49 "열린 결정"과 1:1): refresh 주기·예외 비율 문턱, 토큰 열 "시도" 의미 vs 두 열, 헤더 인증 전환 승인, payload 토큰 해시 정책(concierge 포함·Map 제외) 승인, reverse `NOT_FOUND`에서 within-radius 추가 호출 여부, 설정 키 직접 upsert(allowlist 밖) 승인, MCP replay 조건부 닫음, `SIDO_ALIASES` 등 범위 밖 drift 백로그화, sessionStorage 시군구 선택 자동 해제 여부. geo ADR-069·Map ADR-109 번호는 각 저장소 문서 PR 머지로 확정.

## 2026-10-08: 운영 UI live E2E 확대

- [실행 가이드](live-ui-testing.md)와 운영 전용 config를 추가했다. 로그인·메뉴 21, 폼·작업 22, 운영·Dagster 19, 장소·검수 22, 기존 지도 복구 6개로 총 90개다. 작업자 1개·자동 재시도 0, 실제 조회와 브라우저 장애/fixture를 구분하고 운영 domain write·provider 검색을 막는다.
- 최초 baseline은 하니스 오류 수정과 제품 재현을 위해 중단했다(36 통과/29 실패/14 미실행). 별도 진단 5개는 모두 실패했다. 저장된 메뉴의 hydration 오류, Zod4/resolver3 조합의 미처리 예외, 잘못된 Dagster HTTP200의 상태 교체·화면 오류, 320px 설정 넘침을 수정했다. 첫 전체 후보 실행은 72 통과/18 실패/skip0/flaky0이며 결과를 보존했다.
- 첫 전체 후보의 Dagster 13개는 실제 degraded 응답으로 실패했고 API에는 ReadTimeout이 기록됐다. 이후 같은 운영 컨테이너의 직접 조회는 8회 모두 정상으로 회복했다. UI 시험에서 공유 native 서비스를 재시작하거나 timeout을 늘려 숨기지 않았다. 일시 조회 지연의 근본 원인은 아직 특정하지 않았다.
- 모바일 결과 첫 로드의 자동 선택 행 `scrollIntoView`가 전체 문서를 움직여 메뉴·지도를 밀어내는 현상을 추가로 확인했다. 장소 목록 scrollport만 움직이도록 변경했다. 선택 필터 초기화는 첫 장소 자동 선택이라는 기존 계약에 맞춰 검증한다.
- 독립 리뷰의 요청 취소·늦은 응답 마커 검증 누락을 보강했다. 제품 fetch signal abort를 하니스 정리 전에 관측하고, 늦은 A 응답 이후 B 마커·popup과 A 부재를 확인한다. 리뷰 원문과 초기 실패 기록은 비공개로 보존한다. 최종 결과는 아래와 같다.

- 두 독립 적대 소스 리뷰 PASS/OPEN0 뒤 PR [#246](https://github.com/digitie/kor-travel-concierge/pull/246)을 병합했다(`f4732b9`). 정확한 요청 signal 검증을 포함한 최신 후보 전체는 90/90 PASS, 실패·skip·flaky0, retries0이었다. Manager canonical projection과 전역 mutation 잠금에서 검증한 UI 이미지만 반영하고 이전 이미지·8개 소스를 복구용으로 보관했다. API/MCP/code-server/공유 daemon/webserver ID는 유지됐고 관리자 hash가 비어 있지 않다.
- 첫 공개 전체는 89 PASS/1 FAIL/skip0/flaky0이었다. 설정 GET 응답 전 `count()`로 0개를 즉시 검증하던 하니스 대기 누락이다. 정확한 GET200과 `toHaveCount(9)` 렌더 대기를 추가하고 입력 개수·password 빈 값·4000자 경계 조건을 유지했다. 수정 단건 후보 PASS, 두 독립 좁은 리뷰 PASS/OPEN0 및 공개 전체 90/90 PASS(실패·skip·flaky0, retries0)를 확인했다. 첫 공개 실패 원문도 보존한다.
- 공개/LAN 실제 login POST200·Set-Cookie, summary200/ok, logout200→summary401, 잘못된 비밀번호401을 확인했다. 배포 소스 8개와 후보 hash가 같고 유지 대상 전체에서 재시작 0회·OOM 없음, API/code-server/공유 daemon/webserver healthy다. 이는 특정 시점 관측이며 최초 native 요약 지연의 근본 원인·장기 안정성을 확정한 것은 아니다.
- Chromium의 실제 UI 조회와 browser fault/fixture 시험을 구분한다. 도메인/Dagster 실행 변경·강제 종료·provider 수집·OS IME·다른 브라우저·최대 GPU/heap/RSS·장기부하 검증은 이 90건에 포함하지 않는다. 시험은 작업자 1개로 실행했고 초기 실패와 원문 증거는 비공개로 보존한다.

## 2026-10-08: 지도 무기한 로딩 복구 보강

- 운영 Chromium의 정상 결과 화면에서 실제 PNG 타일과 장소 마커가 표시됨을 확인했다. 사용자 환경의 최초 지도 로딩 고착 원인은 아직 특정하지 않았으며, 응답이 끝나지 않는 조건을 브라우저에서 재현해 복구 경로를 보강한다.
- 최초 candidate live는 정상 desktop/mobile과 타일 보류 복구 3건을 통과했으나 WebGL 실패 1건에서 실패했다. 설치된 MapLibre 6가 WebGL2 생성 실패 때 throw 없이 미완성 Map을 반환하여 어댑터 fallback도 발생하지 않음을 소스·실행으로 확인했다. 지도 생성 전에 1×1 canvas로 WebGL2를 확인하고 context loss 확인 후에만 실제 지도를 생성한다. 해제 확장이 없거나 loss를 확인할 수 없거나 할당 후 예외가 발생하면 지도 생성·수동 재검사를 막고 새로고침/다른 브라우저를 안내한다. 실제 N150 Chromium의 별도 검사에서는 loss 호출 직후 isContextLost가 true임을 확인했다. 이는 드라이버 메모리 반환 시점을 보장하거나 이후 실제 지도 초기화의 모든 실패를 검출한다는 뜻은 아니다.
- 지도 준비 skeleton의 15초 타이머는 준비·재시도·unmount 시 정리된다. 자동 요청 루프 없이 지도만 다시 마운트하고 상위 장소 목록·선택·카메라 목표를 유지한다. WebGL 초기화 실패도 명시적으로 안내하고 수동 재시도한다.
- 정상 desktop/mobile 실제 타일, 타일 응답 보류→수동 복구, WebGL 초기화 실패→수동 복구, 해제 확장 미지원/loss 미확인의 추가 context 생성 차단 live 회귀 6건을 추가했다. 최종 후보 N150 Chromium live 6건은 모두 통과했다(실제 PNG200·마커·재시도 후 목록/선택 보존 포함). frontend type-check·lint·Vitest 336건·production build를 통과했다. 최종 후보 준비 확인 전 시작한 6건은 연결 실패였으며 결과를 보존하고 준비 후 동일 시험을 재실행했다. 운영 반영·공개 재검증 결과는 아래 기록과 같다.

- 두 독립 적대 리뷰의 최종 제품·문서 PASS/OPEN0 후 PR #244를 병합했다(`aa0901c8`). Manager 전역 mutation 잠금과 canonical Concierge compose 경로에서 검증한 후보 이미지로 UI만 재생성했다. 이전 UI 이미지·소스는 복구용으로 보관했다. API/MCP/code-server/공유 daemon/webserver ID는 유지됐다.
- 배포 후 공개 N150 Chromium에서 동일 지도 live 6건 모두 통과했다(재시도 뒤 새 PNG200·장소 목록/선택 마커 보존 포함). 공개/LAN login200·Set-Cookie·summary200/ok·logout200→401·잘못된 비밀번호401과 desktop/mobile Dagster·jobs 화면, pageerror/실패 asset0을 확인했다. 배포 소스 SHA가 리뷰한 후보와 같고 UI restart0/OOM 없음, API/code-server healthy다. 사용자 최초 브라우저의 장애 원인을 특정한 것은 아니다.
- 본 작업이 만든 후보 컨테이너 3개와 비공개 브라우저 settings를 정리했다. 초기 실패/최종 증거와 운영 복구 이미지·소스는 보존한다. 최대 GPU/heap 및 운영 중 context loss drill은 미실행이다.

## 2026-10-07: 공용 Dagster 운영 배포와 backend 전환

- PR #242와 Manager #463/#464를 운영 호스트에 반영했다. 두 DB 백업과 소스·이미지 복구 지점을 확보하고 공식 installer/C6c 경로로 배포했다. 기존 APScheduler 중지·drain 뒤 migration `20261006_0030`, 공유 storage migrate·plane 갱신 및 CLI로 `dagster / generation 1` 전환을 완료했다.
- 두 독립 적대 리뷰와 CI를 통과한 Manager 재생성 수정은 legacy 실행자를 다시 띄우지 않는다. API/MCP SDK 분리와 UID10001·2GiB 제한, 세 sensor tick·공유 plane health를 확인했다. 다른 다섯 앱의 컨테이너 ID와 health는 유지됐다.
- 공개/LAN 인증 POST·Set-Cookie·summary·logout·401 검증 및 N150 공개 Chromium 3 live E2E를 통과했다. 최초 테스트의 gateway Basic 인증 미주입과 목록 제외 seed를 수정한 뒤 재검증했다. 초기 실패 원문도 보존한다.
- provider 호출 없는 성공·실패 seed의 native/domain 상태를 확인했다. UI 재시작의 새 lineage와 동일 입력 재실패, 이후 같은 batch lane의 빈 결과 작업 성공을 확인했다. retry는 0이며 종료 확인 시 pending/running은 0이다. 테스트 실패 attention만 확인 처리하고 이력은 보존했다.
- 컨테이너 migration의 `/app` 작업 디렉터리와 별도 gateway 인증 조건을 [가이드](dagster-adoption.md)에 기록했다. 운영 강제 종료·timeout·cancel drill, 실제 Whisper 최대 RSS·유료 provider 평가는 이번 배포 검증에서 NOT_RUN이다.

## 2026-10-06: Concierge 공용 Dagster 구현과 격리 검증

- Map·PinVi·Geo 공용 instance의 code location으로 이관하고 DB native owner/attempt/control generation fence를 추가했다. API/MCP 이미지에서 Dagster SDK를 분리했다. Common Python과 로그인·메뉴·실행 대시보드를 사용한다(ADR-48).
- 두 독립 FULL 적대 리뷰에서 preclaim 취소 부활, C 연산 중 guardian hard kill, HTTP client cleanup, 첫 lane UNKNOWN의 예산 독점을 검토했다. 확인된 반례를 수정하고 원문·해시를 별도로 보존했다. dispatch는 tick 시작 lane을 교대하며 기존 partial cursor와 새 generation을 보존한다. 후속 리뷰에서 활성 조회 UNKNOWN의 전체 tick 전파도 수정했다. 실제 Common/ephemeral 저장소의 job별 장애 양방향·복원 회귀는 dispatch와 maintenance에서 보류 범위가 해당 job에 한정됨을 확인했다.
- Linux 전체 backend 945건, 최종 lane/Whisper 예약 수정 후 PostGIS·process/회수 회귀 36건 통과. frontend type/lint·336 tests·production build 통과. 전체 Ruff는 기존 진단 314→302로 남지만 추가 진단은 0이다.
- 실제 native launcher/daemon에서 성공·provider 실패·step crash·정상 SIGTERM·명시 취소·60초 runtime 초과·scoped summary를 실행했다. timeout은 running lease를 보존하고 recovery retry를 증가시킨다. 정상 종료는 retry 0으로 재개한다.
- 실제 Docker UID10001/2GiB cgroup에서 두 lane 동시 실행·job당 한 실행·다음 실행 대기를 확인했다. 합성 provider 각64MiB 조건의 peak는 약947MiB다. 살아 있는 proxy의 module load error도 health가 거부하며 기존 Manager incarnation reaper는 이전 실행만 실패로 마감했다.
- N150 Linux Chromium에서 격리 production UI 두 live E2E를 통과했다. 실제 native 로그/선택 상세·mobile·domain 작업 화면·degraded last-good·401 폐기·재조회·logout을 확인했다. fault 응답과 실제 native/API 검증을 구분했다.
- 별도 PostGIS DB에서 clean upgrade, owned pending downgrade 거부, drain 뒤 downgrade/reupgrade 및 기존 행·legacy0 보존을 확인했다. 운영 cutover·공개 gateway 배포·실제 Whisper 최대 RSS·유료 provider 호출은 NOT_RUN이다. [전환/복구 가이드](dagster-adoption.md)를 따른다.

## 2026-10-03: 스케줄러 재시도 운영 배포·인증 경로 복구 확인

- **배포**: 정상 종료·메모리 제한·DB 재시도를 포함한 PR #239/#240 이미지를 운영
  스케줄러에 반영했다. Manager의 정식 릴리스 설치와 전역 mutation 잠금 안에서
  스케줄러만 재생성했고, 이미지 revision·init·메모리 2GiB·CPU 2개·종료 유예 180초를 확인했다.
- **검증**: 같은 이미지의 독립 컨테이너가 SIGTERM 뒤 종료 코드 0·OOM 없음으로 마감했다.
  운영에서는 새 예약 스캔이 완료됐고 재시작·OOM·DB 오류 기록이 없었다. 실패 표식이
  복구 후 남지 않는 보완과 분석 lease 회수 관련 추가 회귀 7건도 통과했다.
- **인증**: API에는 있던 YouTube 키가 재생성된 scheduler에는 주입되지 않았다.
  선택적 설정 파일의 상대 경로가 사라져 생긴 403 오류였다. 임시 symlink 대신 운영
  .env에 실제 저장소의 절대 경로를 지정했다. 구체 경로는 로컬 배포 런북에만 기록한다.
  실제 YouTubeClient 요청의 인증 성공을 최소 쿼터 호출로 확인했다.
- **수집 복구**: 정상 재시작 REST API로 실패 lineage를 보존해 수집 2건을 재실행했고,
  두 건 모두 done·진행률 1.0으로 완료됐다. 인증 실패는 자동 재시도하지 않았다.
- **범위**: 독립 테스트 DB·컨테이너와 SSH 터널을 정리했다. UI는 재생성하지 않았다.
  운영 Manager의 backend health는 확인했지만 관리자 로그인 E2E는 필요한 비밀 파일
  경로가 제공되지 않아 미검증이다.

## 2026-10-03: 스케줄러 DB 일시 오류 자동 재시도

- **기동**: DB 초기화·예약 등록은 일시 연결 장애와 DB 복구·트랜잭션 충돌을 구분해
  2·4·8·16·30초 백오프로 복구를 기다린다. 종료 요청으로 대기를 즉시 중단하고
  부분 등록된 예약은 전체 등록 완료까지 실행하지 않는다.
- **작업**: 작업 중 일시 DB 오류는 기본 최대 3회 재시도한다. 실패 세션을 닫고
  소유권 확인·현재 분석 lease 회수·재시도 횟수 저장 뒤 대기열로 돌린다.
  사용자 중지와 정상 종료는 실패 예산을 차감하지 않는다. 재투입 저장도 실패하면
  heartbeat 만료 복구에 맡긴다. 인증·권한·DB 부재·제약·구문 오류는 제외한다(ADR-47).
- **검증**: n150의 독립 PostgreSQL/PostGIS·운영 Python 이미지에서 관련 테스트 75건,
  같은 독립 DB에 연결한 WSL 확장 검증 77건을 통과했다. 한도 초과, 인증 오류의 즉시 실패,
  초기화 복구, 부분 등록 보류, 새 세션으로 완료, 분석 lease 회수, 백오프 중 중지·종료를
  확인했다. 원시 연결 timeout의 DB 작업 재시도도 별도 검증했다. 변경 Python Ruff 통과.
  DB schema와 프론트엔드 변경은 없다.
- **운영**: 앞선 배포를 막던 다른 작업의 호스트 잠금이 해제되어 Manager의 자원 제한
  설정을 정식 설치했다. 재시도 코드의 운영 스케줄러 적용·확인은 별도 배포 검증으로 기록한다.

## 2026-10-03: 스케줄러 정상 종료와 메모리 사용 상한 설계 개선

- **종료**: DB 초기화부터 SIGTERM·SIGINT를 처리하고 신규 예약을 중단한다. 진행 중
  작업에 완료 시간을 준 뒤 취소 정리를 기다려 현재 작업과 분석 lease를 재투입한다.
  사용자 중지와 구분하며 정상 종료는 실패 재시도 횟수를 차감하지 않는다. DB 저장
  실패는 기존 heartbeat 만료 복구로 회수한다. 실행 잠금 연결도 작업 내내 보유한다.
- **메모리**: 운영 자막·Whisper 호출을 자식 프로세스로 격리해 전역 동시성을 각각
  최대 3개·1개로 제한했다. 자식 RSS·시간·결과 크기 제한을 적용하고, 취소 시 다운로드와
  FFmpeg 프로세스 그룹·임시 파일까지 회수한다. 모델 메모리는 자식 종료 시 반환된다.
  실행자 익명 메모리 임계값에서 신규 claim을 보류한다. Docker의 init·종료 유예·메모리·CPU
  상한도 앱 및 운영 Manager Compose에 적용한다(ADR-46).
- **LLM·지연**: 취소된 LLM 요청은 추가 HTTP 재시도를 막고 현재 스레드 정리를 기다린다.
  내부 주기 작업은 기본 1초 지연 허용 때문에 빠지지 않고 현재 대기열을 처리하도록 수정했다.
- **DB 분석 범위**: 장애 시각에 여러 서비스의 healthcheck가 함께 지연됐지만, 당시
  PostgreSQL 원본 로그는 컨테이너 교체로 없어 정확한 DB 종료 원인은 확정하지 못했다.
  현재 남은 DB 로그에서 반복 복구·재시작은 확인되지 않았다. 따라서 DB 오류를 단순
  일시 환경 문제나 반복되는 schema 결함으로 단정하지 않는다. 예약의 영구 중단은
  재현된 오류 복구 설계 결함이며 앞선 수정으로 해결했다.
- **검증**: n150의 독립 PostgreSQL/PostGIS와 운영 Python 이미지에서 관련 테스트
  126건을 통과했다. 실제 SIGTERM·SIGINT 종료 코드 0, 자식·손자 회수, 메모리·시간 초과,
  전역 전사 동시성, 대기열 복귀·재실행, DB 장애 뒤 타이머 복구를 검증했다.
  운영 DB는 테스트 DB로 사용하지 않았고 DB schema·프론트엔드 변경은 없다.


## 2026-10-03: DB 장애 뒤 스케줄러 실행 중단 수정과 운영 설정 복구

- **원인**: n150의 마지막 예약 스캔은 2026-09-26 13:28(한국 시간)에 완료됐다.
  같은 날 DB 연결 종료로 SQLAlchemyJobStore의 예약 시각 갱신 commit이 실패했다.
  APScheduler 3의 `wakeup()`은 기존 타이머를 취소한 뒤 `_process_jobs()` 반환값으로
  다음 타이머를 등록하므로, 갱신 예외가 밖으로 전파되면 프로세스만 살아 있고 예약은
  중단된다. Docker의 종료 기반 재시작 정책으로는 이 상태를 복구하지 못했다.
- **수정**: `RecoveringAsyncIOScheduler`가 예약 갱신·삭제·다음 시각 조회에서 발생한
  DB 연결 오류를 기존 `jobstore_retry_interval` 주기로 재시도한다. 예외 종류만
  로그에 남겨 SQL·접속 정보가 노출되지 않게 하고, DB 연결과 무관한 오류는 기존처럼
  전파한다. SQLAlchemyJobStore의 연결 풀에도 `pool_pre_ping`을 적용했다.
- **운영 설정**: 재시작 후 예약 스캔과 예정일을 넘긴 수집 2건이 다시 실행됐다.
  수집은 별도로 YouTube 인증 오류를 반환했으며, 배포 설정의 저장소 경로가 없어
  선택적 `env_file`이 생략된 것이 원인이었다. 실제 설정 파일 경로 연결을 복구했다.
  기존 컨테이너 설정값은 변경하지 않았고, 보관된 YouTube 키의 실제 요청 성공도
  확인했다. 실제 키·접속 정보는 저장소 문서에 남기지 않는다.
- **검증**: 수정 전 실제 APScheduler 이벤트 루프에서 갱신·삭제·다음 시각 조회
  장애 3종 모두 실행 중단을 재현했다. 수정 후 WSL 관련 테스트 10건과 Python
  린트·새 파일 포맷 검증, n150 운영 이미지(APScheduler 3.11.3)에서 장애 후
  자동 복구 회귀 테스트 4건을 통과했다. 기존 DB 의존 테스트 34건은 로컬
  테스트 DB가 없어 건너뛰었다. 프론트엔드·DB schema 변경은 없다.

## 2026-09-20: 공용 Postgres 인스턴스(`:11000`)로 실제 데이터 마이그레이션 완료(ADR-44)

- **배경**: 2026-09-19 작업(연결 풀 환경변수화, PR #236)에서 보류했던 실제 데이터
  이전을 이번에 진행했다. `kor-travel-docker-manager` 저장소에 새 공용 instance
  `kor-travel-shared-postgres`(:11000)를 구축하고(PR #360/#361/#363, ADR-44),
  concierge 전용 role `kor_travel_concierge_app`(NOSUPERUSER/NOCREATEDB/
  NOCREATEROLE, `kor_travel_concierge` database 하나에만 권한)을 만들어 ADR-37이
  겪은 격리 실패(role/ACL은 database가 아니라 cluster 전역)를 반복하지 않도록
  했다. 이 저장소(concierge) 자체는 코드 변경이 전혀 없다 — `DATABASE_URL`이
  이미 완전히 환경변수화돼 있었으므로 배포 설정 전환만으로 충분했다.
- **n150 배포 중 발견한 보안 gap**: 최초 배포 직후 실측에서 PostgreSQL이 기본적으로
  모든 database에 `PUBLIC` `CONNECT`를 부여한다는 사실을 확인했다 — db-init이
  role/database/extension만 만들고 CONNECT는 걷어내지 않아, 새 role이 bootstrap
  `postgres` database에도 연결할 수 있었다. `REVOKE CONNECT ... FROM PUBLIC`
  (bootstrap DB + 자기 DB) 후 자기 DB에만 `GRANT CONNECT`로 즉시 고치고 소스에도
  반영했다(PR #361).
- **Hard cutover 절차**: `pg_advisory_xact_lock`이 database 단위라 신·구 instance에
  동시 쓰기가 있으면 동시성 보장이 깨지므로, 완전 정지 후 일괄 전환으로 진행했다.
  1) `ktdctl db-backup create concierge`로 archival 백업(사전 확보) → 2) concierge
  api/mcp/scheduler 컨테이너 정지 → 3) 정지 직후 기존 instance에서
  `pg_dump --format=custom --compress=6` → 4) 새 instance로 `pg_restore`
  (`--no-owner --role=kor_travel_concierge_app`; `pg_stat_statements`/`postgis`
  주석과 옛 instance 전용 `addr` role GRANT 등 4건의 owner-only 경고는 실제 데이터
  손실 없이 무해함을 확인) → 5) 검증(테이블 26개 row count 전부 old=new 정확히
  일치, sequence 값 전부 일치, `alembic_version=20260901_0029`, `postgis_full_version()`
  정상) → 6) `DATABASE_URL`을 새 instance로 전환 → 7) 컨테이너 재기동, `/health`
  200, 실제 연결이 새 instance로 붙는지 확인(신규 instance 7개 연결, 구
  instance 0개 신규 연결).
- **실브라우저 검증**: 로그인 후 결과(2,694건 검수 대기)·작업(작업 이력
  페이지네이션 정상)·수집(1회성 수집 17건 패널, 반복 작업 11건 — 2026-09-12
  phantom 5건 비활성화가 마이그레이션 후에도 유지됨 확인)·검수(개별 후보 상세·
  외부 API 대조) 화면이 모두 실제 데이터로 정상 동작함을 확인했다.
- **후속**: `kor-travel-docker-manager`의 백업 도구(`standalone_backup.py`)가
  일상 백업 대상을 새 instance로 옮기도록 별도 PR(#363)로 수정하고 n150에
  반영, 새 instance를 실제로 백업해 정상 동작을 재확인했다. 옛
  `kor-travel-concierge-postgres`(:12600)는 삭제하지 않고 롤백 안전망으로 그대로
  둔다(현재 쓰기 대상 아님). geo/map/pinvi는 이번 작업 범위 밖이며 ADR-37(프로젝트별
  전용 instance)을 그대로 유지한다. 상세 결정 경위는 `kor-travel-docker-manager`
  저장소 `docs/decisions.md` ADR-44 참조.

## 2026-09-19: 공용 Postgres 인스턴스 전환 대비 — 연결 풀 환경변수화(데이터 이전 없음)

- **배경**: `kor-travel-docker-manager` 저장소 `docs/platform-topology.md` §7이
  같은 날(2026-09-19) "결정된 목표이나 아직 만들어지지 않은" 계획으로, 현재
  프로젝트별 전용 Postgres 인스턴스(concierge는 `kor-travel-concierge-postgres:12600`
  단독 소유) 6개를 포트 `11000` 단일 공용 인스턴스(`dagster_shared`,
  `kor_travel_map`, `kor_travel_geo`, `kor_travel_concierge`, `pinvi` 등 DB를
  한 서버 안에 분리 소유)로 통합하는 5단계 절차를 적어 두었다. 1~4단계는 다른
  프로젝트(map·geo·pinvi)의 Dagster code-server 분리·공유 webserver/daemon
  구성이라 Dagster가 없는 concierge에는 해당하지 않는다. concierge에 실제로
  해당하는 5단계("애플리케이션 DB를 11000으로 이사")는 문서 자체가 "가장 비싸고
  되돌리기 어려운 마지막 단계"로 명시하고, 다른 프로젝트도 1~4단계를 아직
  시작하지 않았다. 사용자 확인 결과 지금은 concierge 쪽 연결 설정만
  파라미터화해 준비해 두고, 실제 데이터 이전(다운타임 수반)은 보류하기로 했다.
- **조사 결과**: concierge의 DB 연결은 이미 `DATABASE_URL` 환경변수 하나로 완전히
  캡슐화돼 있어(코드 안 다른 곳에 호스트/포트/DB명 하드코딩 없음, `alembic/env.py`도
  같은 설정을 공유), 공용 인스턴스로 옮길 때 이 값만 바꾸면 되고 코드 변경은
  필요 없다. 유일하게 준비가 안 돼 있던 지점은 SQLAlchemy 연결 풀 크기가 코드에
  하드코딩(기본값 `pool_size=5, max_overflow=10`)돼 있었다는 것 — 전용 인스턴스에서는
  무의미하지만, 여러 프로젝트가 한 서버의 `max_connections`를 나눠 쓰게 되면 배포
  쪽에서 프로젝트별 예산을 조정할 방법이 코드 배포 없이는 없었다.
- **변경**: `DATABASE_POOL_SIZE`(기본 5)·`DATABASE_MAX_OVERFLOW`(기본 10) 설정을
  추가해 `database.create_engine()`에 연결했다. 기본값이 SQLAlchemy 자체 기본값과
  동일해 지금은 동작 변화가 전혀 없다 — 배포 설정(`.env`)만으로 나중에 좁힐 수
  있도록 통로만 열어 둔 것이다. 실제 DB 데이터 이전, docker-manager의 `11000`
  인스턴스 구축, prod `DATABASE_URL` 전환은 이번 작업 범위 밖이며 별도로 진행한다.
- **검증**: 신규 테스트 2건(기본값 유지 확인, 설정값 반영 확인 — 엔진 생성은 실제
  연결을 만들지 않는 lazy 동작이라 DB 없이 검증 가능)을 포함해 backend pytest
  322건 통과, ruff clean.

## 2026-09-14: 해외 장소 필터링 프롬프트 강화 + 지도 선택 시 줌 강제 버그 수정

- **해외 장소 필터링 강화**: `batch_poi.py`의 POI 추출 system instruction(정리
  단계 프롬프트)이 국내/해외 불확실 시 `is_domestic`을 `true`(국내)로 기본
  처리하도록 지시하고 있었다 — 하지만 실제 자동확정 게이트(`geocode_service.py`
  `_evaluate_identity_gates`)는 정반대로 `is_domestic is True`만 자동확정을
  허용하고 `None`/`False`는 검수 대기로 fail-close하도록 설계돼 있어, 프롬프트의
  fail-open 기본값이 게이트의 fail-close 설계를 무력화하고 있었다(불확실한 해외
  장소가 `true`를 받아 지오코딩·자동확정까지 통과할 수 있었음). 지시문을
  fail-close로 뒤집고("확실하지 않으면 false로 둔다"), 장소명만이 아니라 자막
  전체 맥락(국가·도시명, 통화·비자·시차·항공편 언급, 영상 전체가 해외
  브이로그 맥락인지)으로 판단하도록, 체인점(스타벅스 등)을 브랜드명만으로
  국내로 단정하지 말라는 지침을 보강했다. `is_domestic=False`로 걸러진 후보는
  삭제되지 않고 "해외(국내 아님) — 검수 필요" 사유로 검수 큐 기본 뷰에 그대로
  남는다(`batch_poi_service.py`/`routes.py` 확인) — 확실치 않은 국내 장소를
  놓치는 비용(검수 1클릭)이 해외 장소를 국내로 잘못 들이는 비용보다 작다는
  판단. `visual_extraction.py`의 별도 비전 추출 경로는 `is_domestic=True`
  고정을 그대로 두되(자동확정은 `source_kind`가 `_RECALL_SOURCE_KINDS`에
  속해 `is_domestic` 값과 무관하게 막히므로 안전), 이제는 사실과 다른
  "batch_poi와 같은 규약을 따른다"는 주석을 실제 divergence를 설명하도록
  고쳤다. 신규 테스트로 fail-close 문구가 실제로 프롬프트에 있고 옛 fail-open
  문구는 없는지 고정했다.
- **지도 POI 선택 시 줌 강제 버그 수정**: `VWorldMap.tsx`의 `activeCameraTarget`이
  `currentZoom`(지도 자체의 실시간 줌 상태)에 계속 의존해, 장소가 선택된 동안
  지도에서 줌/이동 제스처가 끝날 때마다(`onZoomEnd`/`onMoveEnd`) 다시 계산되고
  있었다. 이 재계산이 매번 `Math.max(currentZoom, FOCUS_ZOOM)`로 다시 clamp돼,
  선택된 장소가 있는 동안 사용자가 지도에서 직접 FOCUS_ZOOM(12) 아래로 축소하면
  라이브러리가 즉시 그 값으로 다시 튕겨 올렸다 — "리스트에서 다시 클릭하면
  초기화되는 건 맞지만, 지도에서 직접 줌을 바꿀 수 없는" 버그였다. 선택
  대상이 "새로" 바뀐 시점(장소·`focusKey`·좌표 중 하나라도 달라졌을 때)에만
  그 순간의 줌을 한 번 캡처해 고정하도록 바꿔, 이후 지도에서 사용자가 직접
  줌을 바꿔도 다시 계산되지 않게 했다. `focusKey` 없이 좌표만 바뀌는
  `ReviewWorkspace`(폼에서 좌표를 고치는 동안 `selectedPlaceId`는 고정
  sentinel)도 함께 커버하도록 좌표 자체를 pin 시그니처에 포함했다.
- **검증**: 프롬프트 변경은 2인 규모 독립 리뷰(백엔드 정합성/프런트 UI 대신
  각 변경 전담 1인씩) + backend pytest 320건(신규 1건 포함)·ruff clean으로
  검증했다(LLM 판단 자체는 로컬에서 실제 호출 없이는 검증 불가 — 스키마/파싱
  계약은 변경하지 않음을 diff로 확인). 지도 줌 수정은 리뷰가 `DestinationWorkspace`
  (목록·마커 클릭 모두 `focusKey` 증가 확인)와 `ReviewWorkspace`(좌표 편집 경로)
  양쪽을 코드로 추적해 문제없음을 확인했고, n150에 배포해 실브라우저로 장소
  선택 후 지도 확대 컨트롤로 FOCUS_ZOOM 아래까지 직접 축소해도 더 이상
  튕겨 올라오지 않음을, 그리고 목록의 다른 장소를 클릭하면 여전히 정상적으로
  재포커스됨을 두 차례(연속 선택) 확인했다.

## 2026-09-12: 1회성 수집 이력 노출 + phantom 반복 대상 버그 수정, 작업/작업 상세 UI 정리

- **배경**: "수집 페이지에는 없는데 작업 페이지에 이력은 계속 남는 수집작업이 있다"는
  지적('대구 맛집' 등)으로 조사한 결과, `ingest_service.mark_source_target_crawled`가
  1회성 harvest(반복 검색 미체크)에도 `SourceTarget` 행을 무조건 생성하고 있었다.
  `SourceTarget.is_active` 기본값이 `True`라 이 phantom 행이
  `source_scan_service.list_due_targets`(스캐줄러 실행 대상 조회)에는 계속 걸리면서도,
  `list_recurring_targets`(수집 화면 "반복 작업" 목록)는 `scan_interval_minutes IS NOT NULL`
  조건으로 필터링해 화면에서는 완전히 보이지 않았다 — "관리할 방법이 없는 채로 계속
  재실행되는" 정확한 원인이었다. 실제 prod DB에서 부산 맛집·대구 맛집(키워드)과
  채널 2개·재생목록 1개, 총 5건의 phantom 행을 확인했다(가장 오래된 건 2026-06-21
  생성, 3개월째 재실행 중).
- **수정 1 — 근본 원인**: `mark_source_target_crawled`가 이미 등록된 `SourceTarget`
  행이 있을 때만 `last_crawled_at`을 갱신하도록 바꾸고, 없으면 아무것도 만들지 않고
  `None`을 반환하도록 고쳤다(`backend/ktc/etl/ingest_service.py`). 반복 등록은 오직
  `source_scan_service.upsert_recurring_target`(사용자가 "반복 검색"을 켰을 때,
  `routes.py::start_harvest`에서 호출)만 담당한다.
- **수정 2 — 1회성 수집 이력을 수집 화면에 노출**: `routes.py`에
  `_run_source_target_id()`(payload의 `source_target_id`를 읽어 반복/1회성을
  구분)와 신규 `GET /runs/one-time-harvest` endpoint를 추가했다. 이 endpoint는 최근
  harvest 200건을 넓게 훑어 반복 대상에 묶이지 않은 것만 대상별 최신 1건씩 골라
  돌려준다(일반 `GET /runs?job_types=harvest`에 그대로 얹으면 반복 대상 실행과 페이지
  예산을 공유해, 반복 스캔이 잦으면 최근 1회성 이력이 밀려날 수 있어 별도 endpoint로
  분리). `CollectWorkspace.tsx`에 "최근 1회성 수집" 패널을 추가해 대상·상태·최근
  실행·상세/다시 시작/삭제 액션을 보여준다.
- **수정 3 — "기본"/"미분류" 설명 보완**: 수집 화면 "반복 작업" 표와 작업 화면
  "작업 이력" 표 양쪽의 "기본" 칼럼 헤더를 "기본 카테고리"로 바꾸고 `HelpTip`으로
  "새 장소의 카테고리를 자동으로 정하지 못했을 때 대신 저장할 값 — '미분류'는 이 값을
  지정하지 않아 자동 분류 실패 장소가 카테고리 없이 검수 큐에 남는다는 뜻"이라는 설명을
  달았다.
- **수정 4 — 작업 이력 표 UI 일관성**: 상세/다시 시작/삭제/중지 버튼에 공용
  `ACTION_BUTTON_WIDTH_CLASS`(`RunActionButtons.tsx`에서 export, 8곳 중복 제거)를
  적용해 라벨 길이(2~4자)에 무관하게 폭을 통일했다. 행 padding을 `py-2`→`py-3`로
  늘리고 액션 칸을 `flex-wrap items-start`로 바꿔 버튼 수가 행마다 달라도 위치가
  들쭉날쭉하지 않게 했다.
- **수정 5 — 작업 상세 화면 밀도·배치**: "세부 정보"의 재시도/등록/시작/종료를
  라벨:값 한 줄(`MetricGrid`)로 바꾸고(페이지 변형은 단일 컬럼 유지 — `xl:` 좁은
  사이드바 폭에서 2컬럼 강제 시 등록/시작/종료 같은 날짜 값이 눌리는 문제를 피함),
  "영상 처리" 섹션을 "세부 정보" 바로 다음으로 올리고 "로그"는 화면 맨 아래로
  내렸다(`JobDetailView`에 `hideLog`/`afterDetails` prop 추가). 대상/최근 오류처럼
  길이가 정해지지 않은 값은 한 줄로 자르지 않고 줄바꿈하도록(`wrap` 필드) 예외를 뒀다
  (hover 전용 title 툴팁은 터치 기기에서 확인할 수 없어 위험 회피).
- **검증**: 2인의 독립적 적대적 리뷰(백엔드/프런트)에서 실질 결함 없음을 확인했고,
  리뷰가 지적한 미세 이슈(1회성 패널이 반복 실행 트래픽과 페이지 예산을 공유해
  밀려날 수 있는 문제, 대상/최근 오류 필드의 한 줄 자르기 회귀, 버튼 폭 클래스
  8곳 중복)를 모두 반영했다. backend는 n150 실제 Postgres에 disposable DB를 만들어
  101건(신규 7건 포함) 통과, frontend는 lint·type-check·Vitest 336건·프로덕션
  build를 통과했다. n150에 배포해 실브라우저로 세 화면(수집/작업/작업 상세)을 모두
  확인했고, prod DB의 phantom `source_targets` 5건(부산 맛집·대구 맛집 포함)을
  실제 삭제 API(`DELETE /source-targets/{id}`)로 비활성화했다.
- **인프라 참고**: 배포 중 `nohup ... & disown`(및 `setsid` 추가)로 백그라운드
  실행한 원격 빌드가 SSH 연결 종료와 함께 또 소리 없이 사라지는 문제를 이번엔 근본
  원인까지 확인했다 — n150의 `digitie` 계정이 `Linger=no`라 로그인 세션이 끝나면
  systemd-logind가 그 세션의 cgroup(및 그 안의 모든 프로세스)을 정리한다.
  `setsid`는 새 POSIX 세션만 만들 뿐 이 cgroup에서는 벗어나지 못한다. 해결책은
  `sudo systemd-run --unit=<name> --collect --property=StandardOutput=append:<log> -- <cmd>`
  로 로그인 세션과 무관한 system-level transient unit을 띄우는 것이며, 이후 모든
  재빌드를 이 방식으로 전환해 안정적으로 완료했다.

## 2026-09-11: DeepSeek-V4.0-Flash(`deepseek-v4-flash`) 지원 완전 제거, V4.1-Flash를 단일 기본으로

- **배경**: 직전 커밋(PR #230)에서 DeepSeek-V4.1-Flash 신규 식별자 `deepseek-flash`를
  추가하면서, prod가 이미 쓰고 있던 구 식별자 `deepseek-v4-flash`(DeepSeek이
  V4.1-Flash로 자동 라우팅하는 legacy alias)는 호환을 위해 옵션에 남겨뒀다.
  사용자가 "deepseek 4.0 지원 삭제, 4.1을 기본으로" 요청해 그 legacy alias를
  완전히 제거하고 4.1을 유일한 flash 옵션으로 정리했다.
- **변경**: `config.DEEPSEEK_ENGINE_OPTIONS`에서 `"deepseek-v4-flash"`를 제거했다
  (`("deepseek-flash", "deepseek-v4-pro")`만 남음, `deepseek-v4-pro`는 별개
  모델 라인이라 영향 없음). `.env.example`의 안내 주석도 함께 갱신했다.
- **prod 무음 provider 전환 방지**: 옵션에서 값을 빼기만 하면
  `settings_service.get_all()`이 유효하지 않은 `gemini_engine_version` 값을
  조용히 Gemini 기본값(`gemini-2.5-flash`)으로 폴백한다 — prod의 실제 저장값이
  `deepseek-v4-flash`였으므로, 배포 직전 n150 `system_settings` DB 행을
  `deepseek-flash`로 직접 UPDATE해 이 폴백이 발동하지 않고 DeepSeek Flash를
  계속(정확히는 이미 실제로 라우팅되던 V4.1 모델을 이제 올바른 이름으로) 쓰도록
  마이그레이션했다.
- **테스트**: `deepseek-flash`가 여전히 유효하고 `deepseek-v4-flash`는 거부되는지,
  그리고 마이그레이션 없이 구 값이 남아 있으면 실제로 Gemini 기본값 폴백이
  발동하는지(안전망 동작 자체)를 `test_settings_and_audit.py`에 추가했다.
  기존 `test_llm_client.py`/`test_etl_visual_extraction.py`의 예시 모델 문자열도
  `deepseek-flash`로 갱신했다. 로컬은 PostGIS 미구성으로 DB 픽스처 테스트가
  스킵되는 환경이라, n150의 실제 Postgres/PostGIS 인스턴스에 별도 disposable DB
  (`kor_travel_concierge_pytest_verify`, 검증 후 DROP)를 만들어 세 파일 48건을
  전부 통과 확인했다(다른 무관 파일들의 기존 실패는 이 일회성 검증 환경 자체의
  결함으로 보이며 범위 밖).
- **배포**: PR #232 머지 후 rsync로 backend/docs/.env.example을 n150에 반영하고
  `kor-travel-concierge-api`/`scheduler`/`mcp`를 재빌드·재기동했다(이번엔
  `setsid nohup ... </dev/null` 형태로 첫 시도부터 정상 완료, 캐시 적중으로
  1분 내). 재기동 후 prod `system_settings.gemini_engine_version` 값을
  `deepseek-v4-flash` → `deepseek-flash`로 UPDATE했다(before/after 조회로
  실제 전환 확인). `/health` 200, 세 컨테이너 정상 기동 로그, 컨테이너 내
  `config.py`에 `deepseek-v4-flash`가 더 이상 유효 옵션으로 없음을 확인했다.

## 2026-09-11: job 실패 진단 어려움 원인 3건 수정 + DeepSeek-V4.1-Flash 대응

- **배경**: "job 에러 발생 시 어떤 에러 때문인지 파악이 어렵다. 에러 빈도가 높고 정상
  진행이 안되는 job이 적지 않다"는 지적으로 n150 prod `crawl_runs`를 직접 조회했다(27건
  harvest 실패, 상세 last_error 샘플 30건 확인).
- **원인 1 — YouTube `channels.list`/`playlists.list` id 50개 상한 미분할(결정적,
  영구 실패)**: `pipeline.py`가 검색 결과에서 뽑은 중복 제거 채널 ID를
  `channels_list()`에 통째로 넘기는데(실측 148개), YouTube API는 `id`에 50개 초과 시
  항상 400을 반환한다. 재시도해도 절대 성공하지 않아, 특정 키워드 소스(대구/부산
  맛집 등)의 harvest가 매 스케줄 주기마다 반복 실패했다. `videos_list()`가 이미 쓰던
  50개 청크 분할을 `channels_list`/`playlists_list`에도 적용해 결과를 병합하도록 고쳤다
  (`youtube_client.py`).
- **원인 2 — provider 오류 상세가 재구성 과정에서 소실**: 실제 prod last_error가
  `"DeepSeek 호출 실패(status=None, model=deepseek-v4-flash)"`처럼 원인을 전혀 알 수
  없었다. `gemini_client.py`/`deepseek_client.py`의 `GeminiRequestError`/
  `DeepSeekRequestError`는 이미 상세(재시도 소진 여부·원인 예외)를 메시지에 담고
  있었지만, `llm_client.py`가 이를 버리고 `status`/`model`만으로 새 메시지를
  재구성해 `LlmRequestError`로 던졌다. 원본 메시지를 그대로 싣도록 고쳤다.
- **원인 3 — 응답 중 끊김 예외가 재시도·상세화를 모두 건너뜀**: 실제 prod
  last_error에 `"Response ended prematurely"`(컨텍스트 전혀 없음)가 그대로 남은
  사례가 있었다. `requests.exceptions.ChunkedEncodingError`는 `(Timeout,
  ConnectionError)`의 하위가 아니라 좁은 재시도 catch를 건너뛰어 재시도 없이,
  아무 상세 없이 그대로 전파됐다. `gemini_client.py`/`deepseek_client.py`의 재시도
  catch를 `requests.exceptions.RequestException`으로 넓히고, Gemini/DeepSeek
  표준 오류 응답(`{"error": {"message": ...}}`)에서 message를 추출해 상세에 포함했다.
  단, `MissingSchema`/`InvalidURL` 등 재시도해도 항상 같은 방식으로 실패하는 설정
  버그성 예외는 제외해 즉시 실패하도록(수십 초 재시도 낭비 방지) 별도 처리했다.
- **적대적 리뷰(fork 1인)에서 발견·반영한 delta**: (a) 새로 추가한 provider 오류
  상세 추출이 YouTube 클라이언트의 `_mask_api_key`와 달리 API 키를 마스킹하지 않아
  `last_error`(DB·운영 콘솔 노출)에 키가 노출될 수 있었다 — 동일한 마스킹 헬퍼를
  Gemini/DeepSeek 클라이언트에도 추가. (b) `batch_poi_service.py`의 429 쿼터 보류
  판정이 `"429" in message` 부분일치였는데, 상세가 풍부해진 메시지에서 우연한 오탐
  가능성이 생겨 `"status=429"` 형식으로 좁혔다(`status_code` 필드는 재시도 소진
  경로에서도 이제 신뢰 가능해 1차 판정으로 충분하다). (c) 넓힌 `RequestException`
  캐치가 위 설정 버그성 예외까지 재시도하던 문제(원인 3 서술의 즉시 실패 처리로 반영).
- **DeepSeek-V4.1-Flash 대응**: DeepSeek가 2026-09-09 `DeepSeek-V4.1-Flash`를
  출시하며 공식 식별자를 `deepseek-flash`로 바꿨다(api-docs.deepseek.com 확인).
  기존 `deepseek-v4-flash`는 legacy alias로 계속 동작하고(같은 모델로 자동 라우팅,
  동일 Flash 가격) prod 런타임 설정이 실제로 이 값을 쓰고 있어 옵션에서 제거하지
  않았다. `config.DEEPSEEK_ENGINE_OPTIONS`에 `deepseek-flash`를 추가했다
  (`deepseek-v4-pro`는 이름 변경 없음).
- **검증**: backend pytest 319건 통과(신규/보강 테스트 다수 포함: youtube_client
  청크 분할, gemini/deepseek_client 재시도 확대·상세 추출·마스킹·설정오류 즉시실패,
  llm_client 메시지 보존), ruff clean(기존 파일의 무관한 pre-existing 경고 4건
  제외).
- **배포**: PR #230 머지 후 n150에 rsync로 backend 소스를 반영하고
  `kor-travel-concierge-api`/`scheduler`/`mcp`(단일 `Dockerfile.python` 공유
  이미지) 3종을 재빌드·재기동했다. 재빌드 첫 시도 2회는 `nohup ... & disown`으로
  detach했음에도 원격 SSH 세션 종료와 함께 빌드 프로세스가 로그 진행 없이 소리
  없이 사라졌다(원인 미확정 — OOM/dmesg 근거는 없었다); `setsid nohup ... </dev/null`
  으로 완전히 분리한 세 번째 시도에서 정상 완료했다. 재기동 후 `/app/backend`
  내 신규 코드(`deepseek-flash`, `channels_list` 청크 분할 등) 반영과 `/health`
  200, 세 컨테이너 정상 기동 로그(에러 없음)를 확인했다. harvest 반복 실패
  target의 실제 재확인은 다음 스케줄 주기 이후 가능하다.

---

## 2026-09-11: UI Dockerfile이 vendor tarball보다 먼저 npm ci를 실행하는 문제 긴급 수정

- **장애**: vworld-map-web 마이그레이션(PR #228)을 n150에 배포하며 UI 이미지를 재빌드하자
  `npm ci`가 `ENOENT: no such file or directory, open '/app/vendor/vworld-map-web-1.0.0.tgz'`로
  실패했다. `frontend/Dockerfile`이 레이어 캐싱을 위해 `package.json`/`package-lock.json`만
  먼저 COPY하고 `npm ci`를 실행한 뒤 나머지 소스를 COPY하는데, `package-lock.json`의
  `file:vendor/*.tgz` 참조는 실제 tarball 파일이 그 시점에 이미 빌드 컨텍스트에 있어야
  한다 — 레지스트리 의존성만 있던 기존 구조에서는 드러나지 않던 문제다.
- **조치**: `package.json`/`package-lock.json` 다음, `npm ci` 이전에 `COPY vendor ./vendor`를
  추가했다. `package.json`/`package-lock.json`/`vendor`가 바뀔 때만 이 레이어가 무효화되므로
  기존 캐싱 이점은 유지된다.
- **검증**: n150에서 UI 이미지 재빌드 후 정상 기동을 확인한다(배포 진행 중, 상세는 다음
  기록 참조).

## 2026-09-11: VWorld 지도를 공용 vworld-map-web 라이브러리로 교체

- **배경**: `frontend/src/components/VWorldMap.tsx`가 `maplibre-gl`을 직접 명령형으로
  다뤘다(수동 `Map`/`Marker`/`Popup` 생성, DOM 스타일 조작, `ResizeObserver`). 사용자
  지시로 형제 모노레포 `maplibre-vworld-react`의 `vworld-map-web` 패키지(`pinvi`가 이미
  같은 방식으로 소비 중)를 채택해 선언형 API로 교체했다. npm에 배포하지 않는 패키지라
  모노레포 HEAD(`ffa5523`)에서 새로 빌드한 tarball을 `frontend/vendor/`에 vendoring하고
  `package.json`에 `file:` 의존성으로 추가했다.
- **구현**: `VWorldMapView`(동적 import, `ssr:false`) + `Marker`(숫자 배지를 `children`으로
  포팅) + `Popup`(선택된 장소에만 렌더)으로 재작성했다. 외부 prop 계약(`places`,
  `selectedPlaceId`, `onSelectPlace`, `focusKey?`)과 두 소비처(`DestinationWorkspace`,
  `ReviewWorkspace`)는 변경하지 않았다.
- **적대적 리뷰 2인에서 발견·수정한 회귀**:
  - **[BLOCKER]** `VWorldMapView`는 `apiKey`가 비어 있으면 지도·마커·팝업을 전혀
    마운트하지 않고 fallback만 렌더한다(설계상 동작). 키 없는 개발 환경에서도 마커
    클릭 UX가 동작해야 하고(`ktc.spec.ts`가 이를 전제로 마커 버튼을 찾아 클릭) 실제로
    로컬 검수 워크플로도 이를 요구하므로, 항상 비어 있지 않은 값(실제 키 또는
    `KEYLESS_PLACEHOLDER_KEY`)을 넘겨 지도는 항상 뜨게 하고, 실제 키 부재는 별도
    오버레이 배지("VWorld 지도 키 없음")로 알린다.
  - **[MAJOR]** 선택 해제 시 `cameraTarget`이 `undefined`가 되면 라이브러리가 이를 기본
    `center`/`zoom` prop(국가 전체 뷰)으로 간주해 그쪽으로 `easeTo`한다 — 목록
    필터/정렬 변경마다(선택이 매번 초기화됨) 원치 않는 축소→재확대가 발생했다.
    마지막 초점을 state로 기억해 선택 해제 시에도 카메라를 제자리에 둔다.
  - **[MAJOR]** `geolocate`/`scale`이 기본값 `true`라 브라우저 위치 권한 팝업과 스케일
    바가 새로 나타났다. `geolocate={false} scale={false}`로 이전과 동일하게(내비게이션
    컨트롤만) 맞췄다.
  - **[MINOR]** `Popup`의 `closeOnClick` 기본값이 `true`이고 한번 닫히면 같은 인스턴스가
    되살아나지 않아, 지도 배경을 한 번만 클릭해도 이후 어떤 장소를 선택해도 팝업이 다시
    뜨지 않았다. `closeOnClick={false}`로 고정.
  - `data-marker-number` 대신 라이브러리의 `interactionId` prop(→ `data-interaction-id`)으로
    선택 마커 식별 hook을 복원하고, `tests/e2e/live-shell.spec.ts`의 관련 selector를 갱신했다
    (`tests/e2e/ktc.spec.ts`의 `#vworld-map-container`/`data-status` 단언은 변경 불필요).
  - 알려진 채택 한계(후속 과제로 남김): 라이브러리 `Marker`의 root가 `role="button"`+
    `aria-label`만 갖고 `tabindex`/키보드 이벤트가 없어, 기존 실제 `&lt;button&gt;` 대비
    키보드 접근성이 후퇴한다 — 현재 E2E는 이를 검증하지 않으며, 근본 수정은
    `maplibre-vworld-react` 쪽 `Marker` 컴포넌트 보강이 필요하다.
- **검증**: `.env.local`에 로컬 전용 관리자 계정(PBKDF2 해시)·세션 시크릿을 임시로 구성해
  실제 로그인 → 목록 클릭 → 지도 마커 선택·포커스·팝업 → 배경 클릭 후 다른 장소 선택 시
  팝업 복원까지 실브라우저로 확인했다(로컬 PostgreSQL 미구성으로 공식 Playwright E2E
  하니스는 n150에서 별도 확인 예정). frontend lint·`tsc --noEmit`·Vitest 336건·
  `next build --webpack`을 통과했다.

## 2026-09-04: mcp 서비스 crash-loop 긴급 수정 (mcp 2.x 전이 의존성)

- **장애**: Prometheus/로그인 정렬 변경 배포로 backend 3서비스(api/mcp/scheduler,
  공용 이미지)를 재빌드하자 `kor-travel-concierge-mcp-latest`가 `Restarting`으로
  crash-loop했다. `ktc/mcp_server/server.py`가 `from mcp.server.fastmcp import
  FastMCP`(v1 API)를 쓰는데, `requirements.txt`에 `mcp` 패키지가 직접 선언되지
  않고 다른 패키지의 전이 의존성으로만 상한 없이 들어와 있었다 — 이번 재빌드의
  `pip install`이 방금 나온 `mcp 2.1.1`(breaking change: `FastMCP`→`MCPServer`)을
  집어 기존 코드가 깨졌다. mcp 서비스는 이 배포 이전에도 원인 불명으로 3일째
  정지 상태였어서(`Exited (0)`) 이번 강제 재생성 전까지 드러나지 않았다.
- **조치**: `backend/requirements.txt`에 `mcp<2`를 직접 선언(전이 의존성에서 명시
  의존성으로 승격)했다. 로컬에서 `mcp==1.29.1` 해석·`from mcp.server.fastmcp import
  FastMCP` import·`ktc.mcp_server.server.build_server()` 성공을 확인했다.
- **검증**: backend mcp 관련 pytest(스킵 제외 전부 통과), n150에서 backend 3서비스
  재빌드·재생성 후 `kor-travel-concierge-mcp-latest`가 `Up`으로 안정화됨을 확인한다
  (배포 진행 중, 상세는 다음 기록 참조).

## 2026-09-04: 로그인 CSRF Origin 검사를 kor-travel-docker-manager와 정렬

- **비교**: `kor-travel-docker-manager`의 `require_frontend_origin`은 Origin 헤더가
  없으면 403으로 거부하는 반면, concierge의 `requestHasSameOrigin`은 Origin 헤더
  부재를 통과시켰다. 세션/rate-limit 영속화(docker-manager는 DB 감사 로그로 계산,
  concierge는 in-memory)와 CIDR 기반 trusted-proxy(docker-manager는 raw socket
  peer를 CIDR와 대조)도 비교했으나, 전자는 concierge가 단일 컨테이너로 충분하고
  후자는 Next.js App Router `NextRequest`에 raw socket peer 접근자가 전혀 없어
  (`.ip`/`.geo` 제거됨, 헤더만 존재) 헤더만으로 재현하면 위조 가능한 보안 착시가
  된다고 판단해 범위에서 제외했다. 사용자 지시로 Origin 거부만 정렬한다.
- **조치**: `frontend/src/lib/auth.ts`의 `requestHasSameOrigin`이 Origin 헤더 부재를
  거부(`false`)하도록 바꿨다. `/api/auth/login`·`/api/auth/logout`만 이 함수를 쓰며
  기존 `INVALID_ORIGIN` 403 + 감사 이벤트 경로를 그대로 탄다. 브라우저는 same-origin
  POST에도 항상 Origin을 보내므로(Fetch 표준) 정상 로그인/로그아웃 흐름에는 영향이 없다.
- **검증**: frontend lint·`tsc --noEmit`·Vitest 336건(기존 "Origin 헤더가 없으면 통과"
  단언을 거부로 갱신)·`next build --webpack`을 통과했다.

## 2026-09-04: Prometheus 기본 수집기를 ktc_ namespace로 정렬

- **문제**: `/metrics`가 앱 지표(`ktc_*`)와 함께 prometheus_client 기본 수집기의
  `process_*`/`python_info`/`python_gc_*`를 접두어 없이 그대로 노출했다. kor-travel
  계열의 서비스별 네임스페이스 관례(concierge=`ktc_`, kor-travel-docker-manager=`ktdm_`)를
  벗어난다.
- **조치**: `ktc/telemetry.py` 모듈 로드 시 기본 `PROCESS_COLLECTOR`/`PLATFORM_COLLECTOR`/
  `GC_COLLECTOR`를 REGISTRY에서 해제하고, 값이 있는 process 지표(`ktc_process_cpu_seconds_total`
  등 6종)만 `ProcessCollector(namespace="ktc")`로 다시 등록했다. `python_info`(정적
  메타데이터)·`python_gc_*`(진단용, 운영 가치 낮음)는 다시 등록하지 않는다 —
  docker-manager의 hand-rolled `ktdm_*` 전용 노출 방식과 같은 "접두어 없는 지표는
  노출하지 않는다" 원칙에 맞췄다.
- **검증**: `generate_latest()` 직접 호출로 `ktc_process_cpu_seconds_total` 존재,
  접두어 없는 `process_cpu_seconds_total`/`python_info`/`python_gc_objects_collected_total`
  부재를 확인했다. 같은 계약을 `test_prometheus_metrics_endpoint_shape`에 추가했다.
  backend 전체 pytest(PostGIS DB 의존 항목은 `KTC_TEST_PG_DSN` 미설정으로 스킵, 나머지
  전부 통과)와 변경 파일 ruff를 통과했다.

## 2026-09-01: 작업 삭제·오류 상세·Prometheus telemetry·운영 콘솔 브랜딩

- **작업 삭제**: 종료된 `done`/`failed`/`cancelled` 작업만 잠금 후 삭제하도록 REST API와
  `/jobs` 액션을 추가했다. 실행 중 작업과 활성 재시작 자식이 있는 원본은 거부하며, 작업
  단계 이벤트·감사 대상만 정리하고 영상·장소·원본 미디어·관찰 이력은 보존한다.
- **오류 진단**: YouTube Data API 오류 응답의 status/reason/API status/message와 재시도
  횟수를 API key 마스킹 후 `last_error`에 남기도록 보강했다. 작업 상세의 `오류 상세` 영역에서
  전체 원인을 읽고 복사할 수 있으며, 실패 작업 UI E2E fixture로 회귀 검증한다.
- **Prometheus telemetry**: 내부 `/metrics` scrape endpoint에 HTTP 요청/처리시간, 현재
  작업 상태, 실패 원인 종류, 작업 삭제 결과를 저카디널리티 label로 노출한다. 기본 접근은
  loopback/Docker 사설 CIDR로 제한하고 필요하면 별도 `X-API-Key`를 요구한다.
- **브랜드명**: 브라우저 title, 로그인 화면, 좌측 메뉴 상단과 접근성 이름을
  `Travel Concierge Admin UI`로 통일했다. 기존 운영 콘솔의 보라색 색상톤은 유지한다.
- **검증**: backend 전체 테스트 `300 passed, 529 skipped`, frontend Vitest `336 passed`,
  lint·type-check·production build를 통과했다. n150 운영에서 `20260901_0029` migration,
  API/UI/scheduler 재생성, UI 인증 hash 길이 87, API health 200, 공개 로그인
  `200 + Set-Cookie`, 잘못된 비밀번호 `401`을 확인했다. Prometheus 컨테이너의 `promtool`
  설정 검증, concierge API target `up`, refresh query value `1`, 최신 UI의 Linux live
  Playwright **5 passed**를 확인했다. 삭제·상세 오류·의도된 오류 mock과 strict HTTP 오류
  수집도 live 시나리오에 포함한다.
- **리뷰·후속 보강**: 두 전문 리뷰어의 백엔드/프론트엔드 적대적 리뷰에서 확인된 확정 회귀를
  반영했다. stop/restart 상태 변경과 audit 기록을 같은 transaction으로 묶고, 상세 삭제 후
  삭제된 run을 다시 조회하지 않도록 했다. 로컬 삭제 assertion을 대상명 기반으로 갱신하고,
  live E2E는 favicon·ResizeObserver 및 명시된 오류 mock만 허용하며 그 밖의 HTTP 4xx/5xx와
  JavaScript 오류는 실패하도록 강화했다. API worker는 최신 execution lock 코드와 함께
  재생성했다.
