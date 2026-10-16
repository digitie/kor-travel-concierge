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

제품은 admin_region_refresh.py, 실제 회귀는 test_admin_region_refresh.py에 한정한다.
새 table/column/setting key/ENV/cron/provider/API DTO는 없다. 최초 설정 저장은
state=baseline/count0/token_advanced=true이며 completed로 표시하지 않는다.
같은 token의 두 번째 noop은 token_advanced=false다.

첫 두 tick reverse·장소쓰기·dirty0, 실제 변경token, 중단재개/오류prefix/신규tail,
baseline marker 정합/형식, 최초 두 행의 원자성·충돌, legacy cursor/progress,
현재token없음/오류 및 공개 settings 편집불가를 회귀로 검증한다.
기존 실제 refresh 시나리오는 다른 저장 token에서 시작해 의도를 명시한다.
전역 fixture로 baseline 회귀를 가리는 자동 사전시드는 하지 않는다.

현재는 설계 커밋이며 구현·새 테스트·운영 적용은 아직 하지 않았다.
source 확인과 계획은 운영 DB의 현재 token 유무·첫 live run 성공을 증명하지 않는다.
제품 검증 뒤 두 독립 적대 리뷰와 root의 별도 merge/배포 판단이 필요하다.
