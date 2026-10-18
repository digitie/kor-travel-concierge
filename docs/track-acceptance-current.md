# Track1/2 현재 계약과 남은 운영 수용

기준은 PR #259 머지 234c851이다. T-199/T-200 구현, 최초 토큰 기준선과 동일 토큰
운영 noop, 변경 토큰·부분 실패·중단 재개의 격리 실제 HTTP/PostGIS 수용 및
Map adapter 저장 계약은 완료했다. 운영 UI91도 통과했다.
[변경 토큰 수용 근거](geo-changed-token-acceptance.md)를 따른다.

운영 변경 토큰 전량 재해결과 daemon 자동 실행은 미검증이다. 같은 운영 데이터에
가짜 토큰을 주입하거나 전량 재수집해 이 조건을 채우지 않는다.
다음 실제 데이터 변경 때 성공 대상 재처리 방지, 미완료 대상만 재개, 최종 토큰 전진과
Map 공급 반영을 운영 증거로 확인해야 한다.

T-201은 구현된 계약의 현재형 문서 정산이다. ADR의 accepted와 운영 모든 조건의
완료는 구분하며, 기존 T-199/T-200의 운영 조건을 소급 통과로 바꾸지 않는다.

## Track2 장애 조건

현재 기본 HTTP client는 connect2초/read10초이며 기존 회귀는 client 생성 인자와
연결 실패 후 상태 보존을 검사한다. 이 객체 주입 시험은 실제 SYN 무응답 실측이 아니다.
실호스트 전원 차단 없이 소유 격리 네트워크에서 연결 단절 효과를 추가 검증할 수 있는지
확인 중이다. Concierge 3초 미만 및 Map MOIS 예산10% 조건의 실제 효과는 아직 완료가 아니다.

## T-200-pre 실제 lane 확인

Manager origin/main397a91ca0df6a53a328127065b41e940dd23eaf0의 정본에
concierge/concierge_admin_region_refresh limit1이 있다. 현재 Concierge CS와 공용
webserver는 동일 읽기 전용 dagster.yaml(SHA256
7925bcdea8472b069b40b7585b6ab8eb8f7cd03d2bfbb5e252755ff60bacef4f)을 사용하며
실제 concurrency.runs.tag_concurrency_limits에도 같은 lane이 존재한다.
이는 정본·현재 파일 반영 수용이며 daemon OFF 상태에서 admission 실행을 측정한 것은 아니다.
초기 검사에서 예전 run_coordinator 경로만 읽어 빈 배열이 나왔으나, 전체 YAML 재귀
검사로 현재 스키마 위치를 확인했다. 빈 배열을 lane 미설정으로 판정하지 않았다.

## 격리 장애 효과의 후속 범위

별도 PR #261에서 동일 제품의 직접 보강 함수를 실제 SYN DROP으로 검사해
2.0192초 실패·상태 보존·연결 회복을 확인했다. 이는 미머지 후속 테스트 증거이며
장소 확정 route 전체 지연·운영 전원 차단·Map MOIS 전체run1440초 조건을 닫지 않는다.
T-201의 문서 정산은 구현/격리 조건과 이런 운영 미검증 항목을 분리하는 범위다.
