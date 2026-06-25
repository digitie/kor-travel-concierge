"""10개 묶음 POI 배치 추출 (Gemini/DeepSeek, JSON 강제).

교정된 자막 N개(≤10)를 `<video_transcripts>` XML로 묶어 한 번에 POI를 추출한다. 시스템
지시문에 카테고리 마스터(8자리 코드표)를 포함해 카테고리를 코드로 분류하고, 각 영상은
서로 교차참조하지 않도록 강제한다. 결과는 입력 video_id(alias)로 역매핑·검증한다
(입력에 없는 alias·미지 코드는 폐기 → 환각/교차오염 차단). Gemini로 가는 경우 키 전역
rate limiter를 통과한 뒤 호출한다.
"""

from __future__ import annotations

import asyncio
import json

from pydantic import BaseModel, Field, ValidationError

from ktc.etl import category_catalog, gemini_rate_limiter, llm_client

POI_BATCH_TEMPERATURE = 0.1

_SYSTEM_TEMPLATE = (
    "너는 유튜브 스크립트에서 구체적인 '장소(POI)' 정보를 정밀하게 추출하고 분류하는 "
    "데이터 엔지니어다.\n"
    "입력된 자막을 분석하여 출연자가 '실제 방문한 장소'만 추출하고 카테고리를 분류하라.\n"
    "단순히 언급만 했거나(예: 나중에 가고 싶다), 광범위한 행정구역(예: 제주도, 서울)은 "
    "제외한다.\n"
    "다음은 절대 POI로 추출하지 마라: 브랜드·체인·프랜차이즈 상호 단독(예: GS25, "
    "스타벅스, 올리브영, New Balance) — 단 특정 지점이 분명하면 지점명까지 포함하라; "
    "앱·서비스·플랫폼 이름(예: 우버, 에어비앤비, 카카오T); 국가 단독(예: 대한민국); "
    "구체적 상호·지명이 없는 일반 명사(예: 숙소, 식당, 카페, 바다, 주차장).\n\n"
    "너는 지금 서로 완전히 다른 N개의 독립된 동영상 스크립트를 보고 있다.\n"
    "video_001에서 포착된 장소나 맥락을 video_002의 장소를 추론하는 데 절대 교차 "
    "참조(Cross-reference)하지 마라.\n"
    "각 스크립트는 완전히 투명한 벽으로 막혀 있다고 가정하라.\n\n"
    "너는 추출된 장소를 사전에 정의된 [카테고리 마스터 테이블]에 기반하여 엄격하게 "
    "분류하는 '데이터 표준화 엔진'이다.\n"
    "장소의 성격을 분석한 뒤 아래 코드표의 8자리 코드 중 하나를 category_code로 선택하라. "
    "적합한 코드가 없거나 불확실하면 category_code를 빈 문자열로 두어라.\n"
    "각 결과의 video_id에는 입력에 준 video_id(예: video_001)를 그대로 써라.\n\n"
    "각 장소가 대한민국(한국) 안에 있으면 is_domestic을 true로, 해외(국외)면 false로 "
    "설정하라. 이 서비스는 국내 여행지만 다루므로 해외 장소는 검수용으로만 남는다. "
    "국내인지 해외인지 확실하지 않으면 true로 둔다.\n\n"
    "### [카테고리 마스터 테이블] (코드<TAB>분류 경로)\n{catalog}\n"
)

# Gemini response_schema (BatchPOIResult 대응). DeepSeek는 프롬프트 첨부 + json_object.
BATCH_RESPONSE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "total_videos_processed": {"type": "integer"},
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "video_id": {"type": "string"},
                    "official_name": {"type": "string"},
                    "location_hint": {"type": "string"},
                    "category_code": {"type": "string"},
                    "timestamp_start": {"type": "string"},
                    "timestamp_end": {"type": "string"},
                    "speaker_note": {"type": "string"},
                    "is_domestic": {"type": "boolean"},
                },
                "required": ["video_id", "official_name"],
            },
        },
    },
    "required": ["results"],
}


class BatchExtractedPOI(BaseModel):
    video_id: str
    official_name: str
    location_hint: str | None = None
    category_code: str | None = None
    timestamp_start: str | None = None
    timestamp_end: str | None = None
    speaker_note: str | None = None
    # 국내 여부(LLM 판정). None=미판정, True=대한민국, False=해외.
    is_domestic: bool | None = None


class BatchPOIResult(BaseModel):
    total_videos_processed: int = 0
    results: list[BatchExtractedPOI] = Field(default_factory=list)


class BatchPOIError(RuntimeError):
    """재시도 후에도 유효한 배치 결과를 얻지 못한 경우."""


def batch_system_instruction() -> str:
    """카테고리 마스터(8자리 코드표)를 포함한 배치 system instruction."""
    return _SYSTEM_TEMPLATE.format(catalog=category_catalog.prompt_catalog())


def build_batch_prompt(items: list[tuple[str, str]]) -> str:
    """items=[(alias, corrected_transcript)] → `<video_transcripts>` XML 사용자 프롬프트."""
    blocks = []
    for alias, transcript in items:
        # 자막이 묶음 경계 태그를 흉내내 영상 경계를 흐리지 못하도록 중화한다(< → ‹).
        safe = transcript or ""
        for tag in (
            "</script>",
            "<script",
            "<video_transcripts",
            "</video_transcripts",
        ):
            safe = safe.replace(tag, tag.replace("<", "‹"))
        blocks.append(f'  <script video_id="{alias}">\n{safe}\n  </script>')
    return "<video_transcripts>\n" + "\n".join(blocks) + "\n</video_transcripts>"


def parse_batch(payload: str, *, valid_aliases: set[str]) -> list[BatchExtractedPOI]:
    """JSON 파싱 + 검증. 입력에 없는 video_id(alias)는 폐기(교차오염/환각 차단),
    이름 없는 항목 폐기, category_code는 카탈로그 검증(미지·미분류→None)."""
    data = json.loads(payload)
    result = BatchPOIResult.model_validate(data)
    out: list[BatchExtractedPOI] = []
    for poi in result.results:
        if poi.video_id not in valid_aliases:
            continue
        if not (poi.official_name or "").strip():
            continue
        poi.category_code = category_catalog.normalize_code(poi.category_code)
        out.append(poi)
    return out


async def extract_batch(
    runtime: llm_client.LlmRuntime,
    items: list[tuple[str, str]],
    *,
    max_retries: int = 1,
) -> list[BatchExtractedPOI]:
    """≤10개 영상 교정자막 배치에서 POI를 추출한다(1콜). 파싱 실패 시 재시도."""
    if not items:
        return []
    system = batch_system_instruction()
    prompt = build_batch_prompt(items)
    aliases = {alias for alias, _ in items}
    last_error: Exception | None = None
    for _ in range(max_retries + 1):
        if not runtime.is_deepseek:
            await gemini_rate_limiter.acquire(
                estimated_tokens=gemini_rate_limiter.estimate_tokens(system, prompt)
            )
        try:
            raw = await asyncio.to_thread(
                llm_client.complete_json,
                runtime,
                prompt,
                response_schema=BATCH_RESPONSE_SCHEMA,
                system_instruction=system,
                temperature=POI_BATCH_TEMPERATURE,
                # 단발 호출(rate limiter가 분당 한도를 강제 → 429는 일일 쿼터 소진 신호).
                max_attempts=1,
            )
            return parse_batch(raw, valid_aliases=aliases)
        except (json.JSONDecodeError, ValidationError) as exc:
            last_error = exc
            continue
    raise BatchPOIError(f"POI 배치 파싱 실패: {last_error}")
