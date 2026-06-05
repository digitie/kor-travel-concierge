import os
from dotenv import load_dotenv

load_dotenv()

def geocode_address(raw_address: str) -> dict:
    """
    외부 REST API (예: Kakao Local / Naver Maps)를 이용해 불완전한 주소명을
    표준 주소와 경위도 좌표로 변환하는 함수
    """
    provider = os.getenv("GEOLOCATION_PROVIDER", "kakao")
    api_key_by_provider = {
        "kakao": os.getenv("KAKAO_REST_API_KEY"),
        "naver": os.getenv("NAVER_CLIENT_ID"),
        "vworld": os.getenv("VWORLD_SERVICE_KEY"),
    }
    api_key = api_key_by_provider.get(provider)
    
    print(f"[Geocode Log] {raw_address} 좌표 변환 시도 중 (Provider: {provider})...")
    
    # Placeholder: 공급자별 공식 REST API 호출
    # 리턴 값 구조 예시
    return {
        "formatted_address": "부산광역시 해운대구 우동 124",
        "latitude": 35.1587,
        "longitude": 129.1604,
        "success": True
    }

def enrich_destination_description(name: str, address: str) -> str:
    """
    Gemini API를 이용해 확보한 실제 정밀 주소와 위치 메타정보를 기반으로,
    여행지 소개글을 한층 더 상세히 보완하는 로직
    """
    print(f"[Gemini Log] {name} ({address}) 위치 기반 소개글 고도화 진행...")
    return f"{name}은 {address}에 위치한 명소로, 사계절 내내 많은 국내외 관광객들이 찾는 랜드마크입니다."

if __name__ == "__main__":
    coords = geocode_address("부산 해운대구 우동")
    print(f"변환 좌표: {coords}")
    enriched = enrich_destination_description("해운대 해수욕장", coords["formatted_address"])
    print(f"고도화 소개글: {enriched}")
