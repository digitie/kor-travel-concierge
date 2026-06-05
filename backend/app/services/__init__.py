"""도메인 서비스 패키지 (스캐폴드).

API·MCP·scheduler가 공유하는 도메인 로직을 모은다. T-004 이후 다음 서비스를
구현한다.

구현 대상:
    - crawl_runs 작업 생성/claim/heartbeat 서비스
    - 장소 조회·근접 중복 탐색(공간 함수 캡슐화) 서비스
    - 매칭 검수(needs_review) 보정·병합 서비스
    - audit_logs 기록 서비스
"""
