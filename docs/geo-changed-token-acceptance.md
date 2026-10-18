# Track1 변경 토큰·부분 실패·중단 재개 격리 수용

## 수용 범위

PR #258의 최초 token 기준선 및 동일 token noop 운영 검증에 이어,
변경 token의 재해결과 Map 소비 계약을 고정한다. 제품 backend/frontend 변경은 없다.
운영 토큰 조작이나 daemon 기동은 하지 않았다.

- 실제 loopback HTTP Geo fixture와 Concierge API, 격리 PostGIS를 연결했다.
- 변경 token 정상 처리, 21개 중 1개 HTTP 503, 3개 중 두 번째 요청 대기 중 취소를 검사한다.
- 실패·취소 시 최종 cursor는 이전 token을 유지한다. 이미 commit된 장소는 재호출하지 않는다.
- 중간 changes 응답에는 성공한 장소만 나온다. 복구 후 전체 장소의 동일 identity와 새 코드·token을 확인한다.
- 같은 token 재실행은 noop, 같은 changes cursor 재조회는 빈 응답이다.
- 수신한 HTTP 응답을 별도 Map 최신 소스의 public adapter와 실제 load_bundles에 전달했다.
  부분 성공만 새 주소를 저장하며 미완료 장소는 이전 주소를 유지한다.
  복구 시 feature identity와 정상 대상 row_revision을 보존하고, 재생 후 source record 중복이 없다.

## 실제 결과

2026-10-19 로컬 WSL Linux에서 Concierge main 9441e2f 기반:
관련 PostgreSQL 회귀 **47 PASS**(새 HTTP 3건 포함).
Map main e46c223의 별도 PostGIS 통합 fixture로 소비자 저장 **3 PASS, 15.47초**.
Map 제품 파일은 수정하지 않았다. 소유 ephemeral DB는 실행 뒤 회수했다.

이는 실제 HTTP로 받은 응답을 별도 소비자 DB에 재생한 계약 통합 검증이다.
두 운영 서비스의 동시 연결, 실제 Geo 데이터 변경, daemon 자동 실행 및 운영 장애 복구를
검증한 것으로 확대하지 않는다. head9893181의 독립 적대 리뷰 2인 모두 OPEN 0으로 확인됐다.
이번 head9893181에서 운영 제품 및 기존 UI 테스트 소스와의 tree/hash 동등성을 확인한 뒤,
새 n150 Linux 브라우저 실행으로 **UI 91/91 PASS, exit0**를 얻었다. 실행 전 API/MCP/CS/UI와
Map 세 runtime의 healthy 상태, 실행 후 전체 runtime fence 및 daemon OFF를 확인했다.
기존 PR #258 결과를 재사용하지 않았다. 저장소에 workflow가 없어 GitHub checks도 없으며,
CI 성공으로 표시하지 않는다. [정산 증거](reviews/2026-10-19-changed-token-acceptance.json)를 따른다.

## 재현

먼저 운영과 분리된 폐기 가능한 PostGIS를 준비한다. backend fixture는 테이블을
drop/create하므로 운영 DSN을 절대 사용하지 않는다.

    cd backend
    KTC_TEST_PG_DSN=<isolated-dsn> KTC_TRACK1_HTTP_EVIDENCE_DIR=<absolute-output-dir> \
      python -m pytest -q tests/test_geo_refresh_http_acceptance.py \
      tests/test_admin_region_refresh.py tests/test_admin_region_baseline.py

다음 Map checkout의 설치된 개발 의존성과 해당 checkout을 사용한다.
Map의 기존 testcontainers fixture가 새 DB를 생성/마이그레이션하고 종료 시 회수한다.
Concierge backend와 별도 Python 프로세스에서 실행하여 tests 패키지 충돌을 피한다.

    cd <map-checkout>
    PYTHONPATH="$PWD/src:$PWD" KTC_TRACK1_HTTP_EVIDENCE_DIR=<same-output-dir> \
      <map-python> -m pytest -c pyproject.toml \
      <concierge-checkout>/scripts/acceptance/test_map_changed_token.py -q -ra

HTTP fixture는 synthetic 좌표/장소/인증 문자열만 사용한다. 출력 JSON에는 운영 데이터나
credentials가 없으며, 선택적 출력 디렉터리는 저장소 밖에 둔다.
