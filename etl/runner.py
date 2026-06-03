import time
from search import refine_query_with_gemini, search_youtube_videos
from summarize import summarize_video_content
from geocode import geocode_address, enrich_destination_description

def run_etl_pipeline():
    print("====================================================")
    print("TripMate Agent ETL Pipeline 구동 시작")
    print("====================================================")
    
    # 1단계: 검색 키워드 분석 및 유튜브 영상 수집
    keyword = "제주도 맛집"
    print(f"\n[1단계] 키워드 탐색 시작: {keyword}")
    refined_query = refine_query_with_gemini(keyword)
    videos = search_youtube_videos(refined_query)
    
    # 2단계: 신규 비디오 요약 및 장소 추출
    print(f"\n[2단계] 유튜브 비디오 요약 및 1차 여행지 데이터 추출")
    extracted_data = summarize_video_content("jeju_vid_999", "아름다운 제주도 월정리 맛집 탐방입니다...")
    
    # 3단계: Geocoding 위치 보정 및 최종 DB 적재
    print(f"\n[3단계] 외부 REST API 지오코딩 및 장소 정보 고도화")
    for dest in extracted_data["destinations"]:
        print(f"장소 처리: {dest['name']} (Raw Address: {dest['raw_address']})")
        geo_result = geocode_address(dest["raw_address"])
        if geo_result["success"]:
            dest["formatted_address"] = geo_result["formatted_address"]
            dest["latitude"] = geo_result["latitude"]
            dest["longitude"] = geo_result["longitude"]
            
            # Gemini 소개글 수정 보완
            dest["final_description"] = enrich_destination_description(dest["name"], dest["formatted_address"])
            
            print(f"-> 최종 변환 성공: {dest['name']} | {dest['formatted_address']} | ({dest['latitude']}, {dest['longitude']})")
            
    print("\n====================================================")
    print("TripMate Agent ETL Pipeline 구동 완료")
    print("====================================================")

if __name__ == "__main__":
    run_etl_pipeline()
