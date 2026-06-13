"""Gemini 기반 파생 키워드 생성.

시드 키워드에 현재 계절 맥락을 넣어 2~3개의 파생 키워드를 생성한다
(`docs/architecture.md` 4.1). 실제 Gemini 호출은 주입형 `generator` 콜러블로
분리해, 키 없이도 결정론적 폴백으로 테스트할 수 있게 한다. T-007에서 Gemini
generator를 연결한다.
"""

from __future__ import annotations

from collections.abc import Callable

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
