# 2026-10-14 T-199 단독 backend/schema 전환

## 범위와 상태

ADR-49가 허용한 T-199 단독 backend/schema 운영 전환과 검증을 완료했다. 이미 검증한 source0dd0e29e의 API·MCP·Dagster code-server 이미지와 nullable0031 migration을 적용했다. T-200 refresh 코드·job 활성화와 T-202b Geo URL 전환은 이번 범위에 넣지 않는다. 운영 frontend는 별도로 검증한 최신 인증 UI를 유지하며 backend 전체 main/T-200 배포 완료로 확대하지 않는다.

검증된 최신 Concierge UI는 그대로 유지한다. 공유 PostgreSQL·Dagster daemon/webserver와 다른 location·job은 재생성하거나 중지하지 않는다. canonical alias를 retag하지 않고 설치된 Manager의 canonical projection에 이번 runtime3개 image ID를 직접 지정해 UI 제외·no-deps/no-build/pullnever로 교체한다.

## 새 전환 기준과 검증

- 전환 전 운영 관찰은 schema0030·backend dagster·generation1·장소1233건이고 Concierge active run/tick·domain busy는0이다. Native DefaultRunLauncher와 해당 location의 정확한3센서 상태를 확인했다.
- 같은 T-199 backend tree의 전체 PostGIS 회귀996 PASS·FAIL/ERROR/SKIP0을 확인했다. 최초 Unix 준비 확인 하니스의991PASS/5접속 setup ERROR와 TCP 준비 확인 뒤 새 전체996PASS를 별도로 보존했다. 제품 수정으로 하니스 오류를 덮지 않는다.
- 현재 PG/API identity와 UI를 고정해 새 DB backup·SHA·PGDMP header·pg_restore 목록을 확인했다. 과거 backup·old cutover anchors를 재사용하지 않는다.
- 운영 제어기는 exact runtime ID/image/env·Manager input·UI 및 공유 anchor fence, 소유 utility/DB명령 완료 확인, 접수 중단→native/domain drain→3센서 capture/pause→migration→runtime3개 교체→건강/0031/행수/세대 확인→원 상태 복원을 적용했다.
- SDK canonical config와 후보 image/source/command/environment를 접수 중단 전에 확인한다. 입장 중단·sensor 변경·migration·activation intent를 먼저 영속 기록하고 각 단계의 결과를 구분한다.
- Docker CLI 또는 utility timeout은 daemon/DB 완료가 아니다. UNKNOWN이면 경쟁 rollback/up를 하지 않고 소유 작업을 재관찰한 뒤 복구한다. nullable0031을 남겨 이전 runtime3개를 복구할 수 있지만 자동 downgrade나 원 태그 UNKNOWN의 소급 완료는 하지 않는다.
- 최종 고정 제어기와 완료 기록을 독립 적대 리뷰2명이 확인하며 실제 전환 뒤 live HTTP/UI 결과를 별도로 기록한다.

## 배포 전 적대 리뷰 반영

마운트 전체 record를 직접 배열 비교하던 검사가 Docker inspect 순서 변화도 foreign 변경으로 판단하는 문제를 발견했다. 실제 공유 webserver 12회 조회 중11회는 순서만 다르고 record 내용·중복 수·identity는 모두 같았다. 전체 record의 canonical JSON 목록을 정렬해 세 보존 검사에 공통 적용했다. Source·Destination·RW·Type·Mode·Propagation·추가 필드 및 항목 추가/삭제/중복 수는 계속 엄격하게 비교하고 Cmd 배열 순서는 유지한다.

제어기 고정 SHA256 `43bda9fb73c9d839f04aca7ec2c2b7bba90187cce24e1c34ed8070bd3337efcd`를 두 리뷰어가 독립 재검토해 PASS/OPEN0을 확인했다. A의 서로 다른84조건, B의 main22/guard18·재정렬18허용/실제변형36거절은 소유 모형이며 운영 E2E에 합산하지 않는다. 새 canonical config-only 검사는 runtime3개를 확인했고 application mutation0으로 통과했다. 최초 제어기 PASS, 후속 P2/BLOCK, 원 dry run 실패를 모두 별도로 보존한다.

최종 전환 결과는 아래 운영 검증에 결박하며 원 검사 실패를 소급 성공으로 바꾸지 않는다.

## 중단 관찰과 소유 복구 보강

첫 전환은 root 운영 helper가 API 이미지의 `/app/backend` 작업 디렉터리에서 root Alembic 설정의 상대 script 경로를 해석해 CommandError로 중단됐다. 실패 utility는 EXIT1·제거 상태로 보존했고 실제 DB를 다시 조회해 schema0030·토큰 컬럼 부재·원 소유 DB 연결0을 확인했다. 경로를 `/app`으로 맞춘 별도 복구 제어기를 두 리뷰어가 검토했다.

다음 재개는 migration 전 센서 조회 도구의 caller TimeoutError로 중단됐다. 후속 관찰에서 정확한 소유 utility가4.3초 만에 EXIT0으로 종료한 사실을 확인했다. 이를 native 계산90초 초과나 원 caller ACK 성공으로 바꾸지 않는다. force없는 삭제1회와 부재를 별도 영수증에 기록하고 원 start-intent·실패 영수증은 보존했다. 새 복구는 Docker RPC 응답 대기 상한만 늘리며 native 계산·DB·job·migration 상한과 중복 실행 금지를 유지한다.

추가 적대 리뷰에서 CLI 기록2개가 같은 PID를 반복해 다른 원 PID의 생존 확인을 건너뛸 수 있는 모형 P2를 발견했다. exact 파일 집합·전체 SHA·고유 정수 PID2·filename별 PID/args SHA·EXIT0/부재를 결합해 반례를 닫았다. 최종 고정 제어기 SHA256 `41ee7189f36890df1407fb1615e96925d59a58b5ba985a7d1e4c9827da8c9532`는 독립2인 PASS/OPEN0과 새 config-only runtime3/application mutation0을 확인했다. 최종 전환·auth·fresh live UI 결과는 아래에서 별도로 확인했다.

## 실제 운영 완료 검증

runtime3 교체의 CLI는 EXIT0으로 종료했으나 원 전환 제어기는 WAITING_HEALTH 단계 AssertionError로 중단됐다. 당시 정확한 실패 프레임이 없어 원인은 미확정으로 보존한다. 후속 직접 관찰에서 세 owned runtime·UI/shared fence·원 CLI3/utility6의 정상 종료와 부재를 확인했다. 별도 finalizer는 원 snapshot SHA·전체7개 baseline identity/environment·candidate image를 결합하는 리뷰 P2를 닫았고 고정 SHA256 `fb421bd4123573803761683d8ae3501a6b9b0ad416accc831d7e4229831e5e32`를 두 리뷰어가 PASS/OPEN0으로 확인했다. migration·up·restart·stop·pause·retag 없이 원 센서 복원1회와 실제 인증만 마무리했으며 원 실패 영수증을 유지했다.

- schema 단일 head0031·nullable VARCHAR40 토큰 컬럼·`is_geocoded` 부분 인덱스를 직접 확인했다. 장소1233건·backend dagster·generation1을 유지했다. 원3센서는 exact origin과 원 `DECLARED_IN_CODE` 상태로 복원했고 Native DefaultRunLauncher를 확인했다.
- API·MCP는 image `0d608b0d`, Dagster code-server는 `0d858086`의 immutable ID로 교체했고 OCI source0dd에 결박했다. 새 owned ID/image/env/command/mount/network/compose identity·API/CS 건강·MCP 실행·restart0/OOMfalse를 확인했다. UI 이미지98217aee와 UI/shared PG/webserver/daemon ID·설정·source7은 전후 동일하다.
- 내부·외부 실제 login POST200/쿠키·보호 API200·잘못된 암호401·logout200·같은 원 cookie 재사용401을 확인했다. 전환 CLI와 새 utility의 positive EXIT0·PID 부재·삭제/부재를 구분했다. 원 R6 실패EXIT1 및 R7 caller timeout/start-intent는 별도 관찰·정리로 보존한다.
- 새 backend/runtime ID에 연결해 공개 운영 UI 전체91 PASS·실패/skip/flaky0·retry0을 새로 확인했다. 로그인/로그아웃·보호 경로·지도 타일/canvas/marker·장소 조회/선택·Dagster·화면크기390/1024/1440 등의 기존 케이스를 사용했다. browser fault fixture와 실제 운영 응답을 구분하며 domain write/provider 비용 호출은 차단했다. 이전 UI91 결과를 이번 backend 전환의 성공으로 재사용하지 않는다.
- 테스트 시작 전과 종료 후 같은 backend3 owned ID/image와 UI/shared/input/source fence를 확인했다. frontend test source와 실제 UI frontend tree의 동일성도 확인했다. backend 전체 PostGIS996 PASS와 최신 인증 frontend376 PASS/lint/type/build·compiled HTTP12의 소스 범위를 유지한다. 소유 fixture/native 효과와 운영 Geo/provider 성공을 합산하지 않는다.
- 최초 추가 검증 하니스는 schema·sensor 실제 조회를 통과한 뒤 실패 영수증에 없는 after metadata를 참조해 KeyError로 종료했다. 해당 실패와 정상 조회 사실을 분리해 보존하고 finalizer의 완료 metadata를 결합한 새 검증으로 전체 결과를 확인했다.
- Concierge 저장소에는 자동 CI workflow가 제공되지 않아 CI PASS로 기록하지 않는다. native·실제 HTTP/UI·고정 source/identity·두 독립 리뷰의 증거를 사용한다. 기존 canonical alias/원 태그 작업의 UNKNOWN은 ACK 또는 rollback 완료로 바꾸지 않으며 다음 전환에도 검증한 immutable image pin이 필요하다.

## 남는 외부 조건

Geo·Weather·Transport의 Odroid live E2E는 장애로 NOT_RUN이며 해당 세 PR의 예외 병합과 분리한다. T-200 배포·첫 refresh에는 Map 토큰 계약 prod 배포·Geo token/backfill·Manager lane 등의 선행이 남는다. T-202b는 정해진 Geo 전환 순서에 따른다. T-199 및 UI 완료를 전체 track의 운영 완료로 확대하지 않는다.

운영 주소·계정·secret·cookie·DB DSN·원문 로그·backup 자체는 이 공개 기록에 포함하지 않는다.
