"""MCP 도구 정의 (스캐폴드).

`docs/architecture.md` 3.2의 도구 목록을 읽기/쓰기로 구분해 등록 메타데이터만
정의한다. 실제 핸들러 구현과 Pydantic 입력 스키마는 T-011에서 채운다.
"""

from __future__ import annotations

# 읽기 도구: 작업 상태 조회 및 장소 조회
READ_TOOLS: list[dict[str, str]] = [
    {
        "name": "get_harvest_status",
        "summary": "수집 작업 상태·진행률·실패 원인·완료 요약 조회",
    },
    {
        "name": "search_existing_places",
        "summary": "적재된 장소를 검색어·반경·카테고리로 검색",
    },
    {
        "name": "get_place_detail",
        "summary": "장소 상세·원본 영상·대표 프레임·위치 보정 근거 조회",
    },
]

# 쓰기 도구: 작업 생성 및 보정/병합/검수 (MCP_WRITE_ENABLED로 통제)
WRITE_TOOLS: list[dict[str, str]] = [
    {
        "name": "harvest_travel_destinations",
        "summary": "검색어·채널·재생목록 기준 수집 작업 생성 후 job_id 반환",
    },
    {
        "name": "correct_place",
        "summary": "장소명·주소·좌표·카테고리·설명 보정",
    },
    {
        "name": "merge_places",
        "summary": "중복 장소 병합",
    },
    {
        "name": "trigger_deep_research",
        "summary": "Gemini Deep Research 작업 트리거",
    },
    {
        "name": "review_unmatched_place",
        "summary": "needs_review 후보 검수(장소명·주소·좌표·카테고리 보정)",
    },
    {
        "name": "resolve_place_candidate",
        "summary": "후보를 확정 장소와 매칭하거나 제외 처리",
    },
]

__all__ = ["READ_TOOLS", "WRITE_TOOLS"]
