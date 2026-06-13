"""검색 결과 정규화·우선순위 점수.

업로드일 최신성, 키워드 유사도, 조회수 대비 참여도를 애플리케이션 레벨에서
정규화해 우선순위 큐에 적재한다(`docs/architecture.md` 4.2).
"""

from __future__ import annotations

from datetime import date, datetime

# 한국어 계절 라벨
SEASON_KO = {"spring": "봄", "summer": "여름", "autumn": "가을", "winter": "겨울"}


def current_season(d: date) -> str:
    """월 기준 계절(`spring`/`summer`/`autumn`/`winter`)."""
    m = d.month
    if m in (3, 4, 5):
        return "spring"
    if m in (6, 7, 8):
        return "summer"
    if m in (9, 10, 11):
        return "autumn"
    return "winter"


def keyword_similarity(query: str, title: str) -> float:
    """공백 토큰 기반 Jaccard 유사도 (0~1)."""
    q = {t for t in query.split() if t}
    t = {tok for tok in title.split() if tok}
    if not q or not t:
        return 0.0
    return len(q & t) / len(q | t)


def engagement_score(view_count: int | None, like_count: int | None) -> float:
    """조회수 대비 좋아요 비율 (0~1)."""
    if not view_count or view_count <= 0:
        return 0.0
    likes = min(max(like_count or 0, 0), view_count)
    return likes / view_count


def recency_score(
    published_at: datetime | None, now: datetime, *, half_life_days: float = 30.0
) -> float:
    """업로드 최신성 지수 감쇠 점수 (0~1)."""
    if published_at is None:
        return 0.0
    age_days = max((now - published_at).total_seconds() / 86_400.0, 0.0)
    return 0.5 ** (age_days / half_life_days)


def composite_score(
    *,
    similarity: float,
    engagement: float,
    recency: float,
    weights: tuple[float, float, float] = (0.4, 0.3, 0.3),
) -> float:
    """가중 합성 점수."""
    ws, we, wr = weights
    return ws * similarity + we * engagement + wr * recency
