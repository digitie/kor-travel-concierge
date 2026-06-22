"""Gemini 기반 파생 키워드 생성.

시드 키워드에 현재 계절 맥락을 넣어 2~3개의 파생 키워드를 생성한다
(`docs/architecture.md` 4.1). 실제 Gemini 호출은 주입형 `generator` 콜러블로
분리해, 키 없이도 결정론적 폴백으로 테스트할 수 있게 한다. T-007에서 Gemini
generator를 연결한다.
"""

from __future__ import annotations

import json
from collections.abc import Callable

from ktc.core.config import get_settings
from ktc.etl import llm_client
from ktc.etl.ranking import SEASON_KO

# generator 시그니처: (seed_keyword, season) -> list[str]
KeywordGenerator = Callable[[str, str], list[str]]


def _fallback_generator(seed: str, season: str) -> list[str]:
    """Gemini 미연결 시 결정론적 파생 키워드."""
    season_ko = SEASON_KO.get(season, "")
    suffixes = [f"{season_ko} 여행", "가볼만한곳", "핫플레이스 추천"]
    return [f"{seed} {s}".strip() for s in suffixes]


def generate_derived_keywords(
    seed: str, season: str, *, generator: KeywordGenerator | None = None
) -> list[str]:
    """파생 키워드를 생성한다. 중복과 시드 자체는 제거한다."""
    raw = (generator or _fallback_generator)(seed, season)
    seen: set[str] = set()
    result: list[str] = []
    for kw in raw:
        kw = kw.strip()
        if not kw or kw == seed or kw in seen:
            continue
        seen.add(kw)
        result.append(kw)
    return result


_DERIVED_KEYWORDS_SCHEMA: dict = {
    "type": "object",
    "properties": {"keywords": {"type": "array", "items": {"type": "string"}}},
    "required": ["keywords"],
}


def make_llm(runtime: llm_client.LlmRuntime) -> KeywordGenerator:
    """선택된 엔진(Gemini/DeepSeek) + 사전 프롬프트로 시드+계절 파생 검색어 generator를 만든다.

    어떤 이유로든 실패하면(키 없음/일시 오류/파싱 실패) 결정론적 템플릿 폴백을
    반환해, keyword expansion이 harvest 전체를 막지 않게 한다.
    """

    def generate(seed: str, season: str) -> list[str]:
        season_ko = SEASON_KO.get(season, "")
        prompt = (
            f'여행 검색 시드 키워드 "{seed}"(계절 맥락: {season_ko})에 대해 '
            "YouTube에서 여행지·맛집·명소를 잘 찾을 수 있는 한국어 파생 검색어 "
            "2~3개를 제안하라. 시드 의미를 유지하되 지나치게 일반적이지 않게 하라. "
            "반드시 주어진 JSON Schema에 맞는 JSON만 출력하라."
        )
        try:
            payload = llm_client.complete_json(
                runtime,
                prompt,
                response_schema=_DERIVED_KEYWORDS_SCHEMA,
                # 단발 호출: 429(쿼터 소진) 시 느린 재시도(~90s)로 harvest가 멈추지 않고
                # 즉시 템플릿 폴백한다. keyword expansion은 best-effort라 안전하다.
                max_attempts=1,
            )
            parsed = json.loads(payload)
            keywords = parsed.get("keywords") or []
            cleaned = [str(kw).strip() for kw in keywords if str(kw).strip()]
            return cleaned or _fallback_generator(seed, season)
        except Exception:
            # keyword expansion은 best-effort: 실패 시 템플릿으로 안전 폴백한다.
            return _fallback_generator(seed, season)

    return generate


def make_gemini_keyword_generator(
    *,
    api_key: str | None = None,
    model: str | None = None,
    timeout_seconds: float = 30.0,
) -> KeywordGenerator:
    """`.env`/인자 기반 production generator (BACK-COMPAT shim → make_llm)."""
    from dataclasses import replace

    runtime = llm_client.LlmRuntime.from_settings(model=model)
    if api_key:
        runtime = replace(runtime, gemini_api_key=api_key)
    if not (runtime.gemini_api_key or runtime.is_deepseek):
        # 키가 없으면 Gemini 경로를 호출하지 않고 템플릿 폴백으로 안전하게 둔다.
        return _fallback_generator
    return make_llm(runtime)


def default_keyword_generator() -> KeywordGenerator | None:
    """Gemini 키가 있으면 Gemini generator, 없으면 None(→ 템플릿 폴백)."""
    if not get_settings().GEMINI_API_KEY:
        return None
    return make_gemini_keyword_generator()
