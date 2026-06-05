"""ETL 2단계 요약 스크립트 (CLI 데모용 placeholder).

실제 자막/전사 provider 체인, Gemini JSON Schema POI 추출, RustFS 저장,
설명 보정본·매칭 후보 생성은 `backend/app/etl/` 패키지
(`transcript`/`poi_extraction`/`media_store`/`summarize_service`)에 구현되어
있다(T-007). 이 파일은 단독 실행 데모 흐름만 유지한다.
"""

import os
from dotenv import load_dotenv

load_dotenv()

def summarize_video_content(video_id: str, transcript: str) -> dict:
    """
    Gemini API를 사용하여 영상 자막(대본)을 파싱하고, 여행지명과 세부 소개를 추출하는 함수
    """
    gemini_key = os.getenv("GEMINI_API_KEY")
    engine = os.getenv("GEMINI_ENGINE_VERSION", "gemini-2.0-flash")
    
    print(f"[Gemini Summary Log] 영상 {video_id} 요약 및 장소 데이터 추출 중 (Engine: {engine})...")
    
    # Placeholder: Gemini API 호출하여 구조화된 정보(JSON)를 추출하는 프롬프트 작성 예정
    extracted_destinations = [
        {
            "name": "해운대 해수욕장",
            "description": "부산의 상징적인 해변으로 넓은 모래사장과 주변의 화려한 스카이라인이 특징입니다.",
            "raw_address": "부산 해운대구 우동"
        }
    ]
    return {
        "summary": "부산의 대표적인 해수욕장과 인근 맛집 코스를 소개하는 영상입니다.",
        "destinations": extracted_destinations
    }

if __name__ == "__main__":
    result = summarize_video_content("test_vid_123", "이곳은 아름다운 부산 해운대입니다...")
    print(f"추출 결과: {result}")
