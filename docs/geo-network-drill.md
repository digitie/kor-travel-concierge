# Geo 연결 단절의 격리 실제 네트워크 수용

제품은 #259 머지234c851 그대로다. Linux의 비특권 user/net namespace 안에서
loopback HTTP server를 실행하고 해당 포트의 SYN만 DROP했다. 호스트 firewall과
운영 서비스·DB·token·daemon은 변경하지 않았다.

현재 enrich_place_admin_codes의 기본 httpx client를 호출했다. transport와 timeout은
주입하지 않고 secret 조회만 synthetic fixture로 대체했다. 정상 응답 후 새 장소로
단절을 검사하고 DROP 제거 뒤 다시 정상 응답을 확인했다.

- 정상:0.0498초, 실제 HTTP 성공.
- 단절:2.0192초에 False, 기존 행정코드·토큰 보존, DROP packet2개, HTTP 요청 추가0.
- 회복:0.0072초, 실제 HTTP 성공. 전체 서버 요청2개.
- 같은 network/user namespace 거절3개와 실제 단절·회복1개, 총4개 회귀 PASS.
- Ruff 및 diff check PASS. [공개 수치와 소스 hash](reviews/2026-10-19-geo-network-drill.json).

단절 구간의 1.8초 이상·3초 미만 assertion으로 즉시 RST를 timeout 성공으로 오인하지
않는다. namespace는 부모와 달라야 하고 single non-root UID mapping을 요구한다.
종료 시 소유 DROP 규칙과 server를 회수하며 부모 namespace는 불변이다.
처음 guard 보강 시 child에서 proc1 namespace 읽기 권한 오류로 수집 전 실패했다.
불필요한 proc1 접근을 제거하고 부모 inode 비교와 UID mapping 검증을 유지한 뒤 통과했다.

## 재현

Linux user namespace, ip, iptables와 설치된 backend 개발 의존성이 필요하다.
운영 호스트에 실행하지 않고 로컬 비특권 사용자로 명시 실행한다.

    python scripts/acceptance/geo_network_drill.py
    python -m pytest -q scripts/acceptance/test_geo_network_drill.py

이 검증은 직접 보강 함수의 연결 단계 지연이다. 실제 장소 확정 HTTP route 전체·DB
commit 지연·운영 호스트 전원 차단을 검증하지 않는다. read timeout은10초로 유지하므로
연결 뒤 무응답은 이번3초 기준에 포함하지 않는다. Map MOIS 전체 run의1440초 실패
기준과 daemon 자동 복구도 별도다. 제품 변경·신규 배포가 없어 기존 UI91 근거를
유지하며 이번 하니스 실행을 새 live UI 실행이라고 표시하지 않는다.
