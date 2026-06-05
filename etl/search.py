"""ETL 1단계 검색 스크립트 (CLI 데모용 placeholder).

실제 비동기 수집 파이프라인(공식 YouTube Data API v3 클라이언트, 파생 키워드,
정규화 점수, 멱등 적재)은 scheduler가 import하는 `backend/app/etl/` 패키지
(`youtube_client`/`keyword_expansion`/`ranking`/`ingest_service`/`pipeline`)에
구현되어 있다(T-006). 이 파일은 단독 실행 데모 흐름만 유지한다.
"""

import os
from dotenv import load_dotenv

load_dotenv()

def refine_query_with_gemini(raw_keyword: str) -> str:
    """
    GEMINI API를 활용하여 검색 키워드를 구체화하고 보정하는 함수 예제
    """
    gemini_key = os.getenv("GEMINI_API_KEY")
    engine = os.getenv("GEMINI_ENGINE_VERSION", "gemini-2.0-flash")
    
    # Placeholder: Gemini API 호출 로직 작성 예정
    print(f"[Gemini Log] {raw_keyword} 검색어 상세화 분석 중 (Engine: {engine})...")
    refined = f"{raw_keyword} 여행 추천 핫플레이스 가볼만한곳 코스"
    return refined

def search_youtube_videos(query: str):
    """
    공식 YouTube Data API v3를 통해 영상을 탐색하는 함수
    """
    youtube_key = os.getenv("YOUTUBE_API_KEY")
    use_official_api = os.getenv("YOUTUBE_USE_OFFICIAL_API", "true").lower() == "true"
    print(f"[YouTube Log] {query} 조건으로 공식 API 신규 영상 탐색 실행 (official={use_official_api})...")
    # Placeholder: YouTube Data API v3 연동 결과 반환 예정
    return []

if __name__ == "__main__":
    test_keyword = "부산 여행"
    refined_q = refine_query_with_gemini(test_keyword)
    print(f"원래 검색어: {test_keyword} -> 상세화 검색어: {refined_q}")
    search_youtube_videos(refined_q)
