"""백엔드 ETL 수집 파이프라인 패키지.

scheduler 단일 실행자와 서비스 계층이 import해 사용한다(ADR-13).

구현 완료(T-006 1단계 수집):
    - youtube_client    : 공식 YouTube Data API v3 비동기 클라이언트
    - keyword_expansion : Gemini 기반 파생 키워드(주입형 generator)
    - ranking           : 업로드일·키워드 유사도·참여도 정규화 점수
    - ingest_service    : video_id 멱등 upsert, 파생 키워드 저장, 채널 워터마크
    - pipeline          : 수집 오케스트레이션(run_harvest)

구현 완료(T-007 2단계 요약·POI):
    - transcript        : 자막/전사 provider 체인(transcript-api→yt-dlp→whisper)
    - poi_extraction    : Gemini JSON Schema POI 추출·재시도(주입형 llm)
    - media_store       : RustFS 저장 추상화 + media_assets 기록
    - summarize_service : 자막 저장→POI 추출→설명 보정본·후보 생성

구현 대상(T-008 이후):
    - 지오코딩, 대표 프레임 추출
"""

from app.etl import (
    ingest_service,
    keyword_expansion,
    media_store,
    pipeline,
    poi_extraction,
    ranking,
    summarize_service,
    transcript,
    youtube_client,
)

__all__ = [
    "youtube_client",
    "keyword_expansion",
    "ranking",
    "ingest_service",
    "pipeline",
    "transcript",
    "poi_extraction",
    "media_store",
    "summarize_service",
]
