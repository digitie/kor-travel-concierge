"""ETL ranking/keyword_expansion 단위 테스트."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from ktc.etl import ranking
from ktc.etl.keyword_expansion import generate_derived_keywords


def test_current_season():
    assert ranking.current_season(date(2026, 4, 1)) == "spring"
    assert ranking.current_season(date(2026, 7, 1)) == "summer"
    assert ranking.current_season(date(2026, 10, 1)) == "autumn"
    assert ranking.current_season(date(2026, 1, 1)) == "winter"


def test_keyword_similarity():
    assert ranking.keyword_similarity("제주도 맛집", "제주도 맛집 투어") > 0
    assert ranking.keyword_similarity("제주도 맛집", "서울 카페") == 0.0
    assert ranking.keyword_similarity("", "무엇") == 0.0


def test_engagement_score_bounds():
    assert ranking.engagement_score(1000, 100) == 0.1
    assert ranking.engagement_score(0, 100) == 0.0
    assert ranking.engagement_score(None, 100) == 0.0
    # 좋아요가 조회수를 넘으면 1로 클램프
    assert ranking.engagement_score(100, 1000) == 1.0


def test_recency_score_monotonic():
    now = datetime(2026, 6, 5, tzinfo=timezone.utc)
    fresh = ranking.recency_score(now - timedelta(days=1), now)
    old = ranking.recency_score(now - timedelta(days=60), now)
    assert fresh > old
    assert ranking.recency_score(None, now) == 0.0
    # 반감기(30일)에서 약 0.5
    half = ranking.recency_score(now - timedelta(days=30), now)
    assert 0.49 < half < 0.51


def test_composite_score_weighting():
    s = ranking.composite_score(similarity=1.0, engagement=0.0, recency=0.0)
    assert abs(s - 0.4) < 1e-9


def test_generate_derived_keywords_fallback():
    kws = generate_derived_keywords("부산", "summer")
    assert len(kws) == 3
    assert all("부산" in k for k in kws)
    assert any("여름" in k for k in kws)


def test_generate_derived_keywords_custom_generator_dedup():
    def gen(seed, season):
        return [f"{seed} a", f"{seed} a", seed, "  "]

    kws = generate_derived_keywords("X", "winter", generator=gen)
    # 중복·시드자체·공백 제거
    assert kws == ["X a"]
