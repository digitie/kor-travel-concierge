# Geo 첫 data_token 기준선 정합

## 문제와 정본

Geo ADR-069 D8:253의 첫 token 기준선 규칙을 따른다. 기존 Concierge main6a7148fa의
admin_region_refresh는 저장 token이 없어도 stale 장소가 있으면 재해결한다.
첫 tick에 저장 후 return만 추가하면 다음 동일 token tick에서 다시 재해결하므로 충분하지 않다.
동일 token 무조건 noop은 기존 신규 stale·오류·중단 재개를 잃으므로 채택하지 않는다.

## 최소 상태 전이

기존 CURSOR/PROGRESS 두 키가 모두 없을 때만 token과
{token,after:0,ceiling:null,phase:"baseline"}을 한 transaction으로 저장한다.
초기 저장은 두 INSERT ON CONFLICT DO NOTHING으로 기존 진행을 덮지 않으며,
하나라도 충돌하면 같은 transaction의 신규 기록을 rollback하고 다음 tick에 재판정한다.

저장 cursor와 baseline marker와 현재 token이 모두 같을 때만 stale가 있어도 noop이다.
실제 token 변경은 기존 save_progress가 marker를 일반 진행으로 바꾼 뒤 원 keyset 처리를 한다.
기존 PROGRESS가 있으면 첫 관측으로 초기화하지 않고 재개를 우선한다.
legacy CURSOR-only+stale, 오류 재시도, 고정 ceiling/단일 wrap, 장소별 commit,
마지막 stale 재검사, dirty와 xmin/좌표/token fence는 유지한다.
기존 명시적 cursor 삭제는 progress가 남으므로 강제 재시도 의미를 유지한다.
두 키를 모두 없애면 새 기준선 관측으로 시작한다.

## 범위와 검증

제품은 admin_region_refresh.py에 한정한다. PostGIS 회귀는 test_admin_region_refresh.py,
외부 연결 없는 설정 SQL 원자성 회귀는 test_admin_region_baseline.py에 둔다.
새 table/column/setting key/ENV/cron/provider/API DTO는 없다. 최초 설정 저장은
state=baseline/count0/token_advanced=true이며 completed로 표시하지 않는다.
같은 token의 두 번째 noop은 token_advanced=false다.

첫 두 tick reverse·장소쓰기·dirty0, 실제 변경token, 중단재개/오류prefix/신규tail,
baseline marker 정합/형식, 최초 두 행의 원자성·충돌, legacy cursor/progress,
현재token없음/오류 및 공개 settings 편집불가를 회귀로 검증한다.
기존 실제 refresh 시나리오는 다른 저장 token에서 시작해 의도를 명시한다.
전역 fixture로 baseline 회귀를 가리는 자동 사전시드는 하지 않는다.

## 구현 및 검증 상태

PR #258의 제품 커밋 0897415는 위 상태 전이를 구현한다. 기존 write_setting은 자체 commit이
없으므로 별도 저장소 helper 없이 insert-only 두 claim을 같은 session에서 commit한다.
형식이 잘못된 baseline marker는 재해결 전에 실패한다. 기존 same-token/no-stale
fast path는 유지한다. 신규 장소는 baseline marker가 유지되는 동안 재해석하지 않고
원래 일반 enrichment 경로를 유지하며, 실제 다음 token 변경 때 기존 stale keyset에 포함된다.

- 원본 main에 새 첫 관측 회귀를 적용하면 장소 재해결에 도달해 실패하고, 수정 뒤
  첫 두 tick 및 원자성·두 번째 쓰기 실패·경합·marker 형식·기존 progress 15건은 통과했다.
  이 집중 SQL 시험은 자기 in-memory SQLite 설정 테이블이며 PostGIS 동시성 증거가 아니다.
- 기존 변경 token/중단 재개/오류·좌표 fence/내보내기 회귀는 과거 token을 명시하도록
  전제만 보강했다. 첫 관측/다음 tick/기존 progress 우선/실제 PostgreSQL 충돌 회귀도 추가했다.
- 로컬 backend 전체는 PG DSN을 전달하지 않은 격리 환경에서 EXIT 0이며 진행 결과
  434 PASS / 612 SKIP다. 실제 PostGIS 회귀는 미실행으로 남긴다.
  첫 시도의 scheduler import 경로 누락 2 collection error와 원본 반례 하니스 경로 오류는
  보존하고, PYTHONPATH 및 원본 모듈 결박을 보완한 뒤 확인했다.

- 변경 Python Ruff 및 frontend type-check·376 tests·lint·production build는 통과했다.
  frontend는 기존 lock과 byte 일치하는 node_modules를 자기 작업 트리에 복사해 검사했다.
- 저장소 backend/scheduler 전체 Ruff는 기존 main 286건 대비 282건으로 실패하며 신규 지적은
  0건이다. 기존 다른 파일을 일괄 수정하지 않았다. 실제 PostGIS와 live Playwright E2E는
  실행하지 않았고 현재 PR의 GitHub check 목록도 비어 있어 CI 통과로 세지 않는다.

운영 DB의 현재 token 유무·첫 live run·배포 효과는 미확인이다.
독립 적대 리뷰 두 명과 root의 별도 merge/배포 판단이 필요하다.
