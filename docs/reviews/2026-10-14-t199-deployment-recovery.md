# 2026-10-14 T-199 단독 backend/schema 전환

## 범위와 상태

ADR-49가 허용한 T-199 단독 병렬 배포를 준비한다. 이미 검증한 source0dd0e29e의 API·MCP·Dagster code-server 이미지와 nullable0031 migration만 적용한다. T-200 refresh 코드·job 활성화와 T-202b Geo URL 전환은 이번 범위에 넣지 않는다. 이 초안은 운영 전환 완료를 주장하지 않는다.

검증된 최신 Concierge UI는 그대로 유지한다. 공유 PostgreSQL·Dagster daemon/webserver와 다른 location·job은 재생성하거나 중지하지 않는다. canonical alias를 retag하지 않고 설치된 Manager의 canonical projection에 이번 runtime3개 image ID를 직접 지정해 UI 제외·no-deps/no-build/pullnever로 교체한다.

## 새 전환 기준과 검증

- 최신 운영 관찰은 schema0030·backend dagster·generation1·장소1233건이고 Concierge active run/tick·domain busy는0이다. Native DefaultRunLauncher와 해당 location의 정확한3센서 상태를 확인했다.
- 같은 T-199 backend tree의 전체 PostGIS 회귀996 PASS·FAIL/ERROR/SKIP0을 확인했다. 최초 Unix 준비 확인 하니스의991PASS/5접속 setup ERROR와 TCP 준비 확인 뒤 새 전체996PASS를 별도로 보존했다. 제품 수정으로 하니스 오류를 덮지 않는다.
- 현재 PG/API identity와 UI를 고정해 새 DB backup·SHA·PGDMP header·pg_restore 목록을 확인했다. 과거 backup·old cutover anchors를 재사용하지 않는다.
- 운영 제어기는 exact runtime ID/image/env·Manager input·UI 및 공유 anchor fence, 소유 utility/DB명령 완료 확인, 접수 중단→native/domain drain→3센서 capture/pause→migration→runtime3개 교체→건강/0031/행수/세대 확인→원 상태 복원을 적용하도록 설계한다.
- SDK canonical config와 후보 image/source/command/environment를 접수 중단 전에 확인한다. 입장 중단·sensor 변경·migration·activation intent를 먼저 영속 기록하고 각 단계의 결과를 구분한다.
- Docker CLI 또는 utility timeout은 daemon/DB 완료가 아니다. UNKNOWN이면 경쟁 rollback/up를 하지 않고 소유 작업을 재관찰한 뒤 복구한다. nullable0031을 남겨 이전 runtime3개를 복구할 수 있지만 자동 downgrade나 원 태그 UNKNOWN의 소급 완료는 하지 않는다.
- 새로운 고정 제어기의 독립 적대 리뷰2명과 실제 전환 후 live HTTP/UI를 통과한 뒤 최종 운영 상태를 기록한다.

## 남는 외부 조건

Geo·Weather·Transport의 Odroid live E2E는 장애로 NOT_RUN이며 해당 세 PR의 예외 병합과 분리한다. T-200 배포·첫 refresh에는 Map 토큰 계약 prod 배포·Geo token/backfill·Manager lane 등의 선행이 남는다. T-202b는 정해진 Geo 전환 순서에 따른다. T-199 및 UI 완료를 전체 track의 운영 완료로 확대하지 않는다.

운영 주소·계정·secret·cookie·DB DSN·원문 로그·backup 자체는 이 공개 기록에 포함하지 않는다.
