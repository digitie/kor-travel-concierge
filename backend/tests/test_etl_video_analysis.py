"""Gemini YouTube URL 분석 서비스 테스트."""

from __future__ import annotations

import json

from ktc.etl import gemini_client, gemini_rate_limiter, video_analysis_service
from ktc.models import (
    ExtractedPlaceCandidate,
    FeatureExportStatus,
    MatchStatus,
    VideoAnalysisRunState,
    VideoAnalysisRunType,
    YoutubeChannel,
    YoutubeVideo,
    YoutubeVideoAnalysisRun,
)


async def test_run_url_summary_analysis_stores_video_and_run(session):
    session.add(YoutubeChannel(channel_id="UC1", title="서울여행자"))
    video = YoutubeVideo(
        video_id="v-url",
        title="서울 골목 여행",
        url="https://www.youtube.com/watch?v=v-url",
        canonical_url="https://www.youtube.com/watch?v=v-url",
        channel_id="UC1",
        channel_name="서울여행자",
        description_raw="익선동과 북촌을 걷는 영상",
    )
    run = YoutubeVideoAnalysisRun(
        video_id="v-url",
        run_type=VideoAnalysisRunType.URL_SUMMARY,
        state=VideoAnalysisRunState.PENDING,
    )
    session.add_all([video, run])
    await session.commit()
    await session.refresh(run)

    captured = {}

    def fake_llm(prompt: str, video_url: str) -> str:
        captured["prompt"] = prompt
        captured["video_url"] = video_url
        return json.dumps(
            {
                "summary": "익선동 한옥거리와 북촌 산책 동선을 소개한다.",
                "creator_perspective": "짧은 도보 여행에 적합하다고 강조한다.",
                "places": [
                    {
                        "name": "익선동 한옥거리",
                        "category": "거리",
                        "timestamp_start": "03:10",
                        "evidence_text": "익선동 골목을 걷는다고 말한다.",
                        "confidence_score": 0.91,
                    }
                ],
                "source_notes": [],
                "overall_confidence": 0.88,
            },
            ensure_ascii=False,
        )

    result = await video_analysis_service.run_url_summary_analysis(
        session,
        video,
        run,
        llm=fake_llm,
        model="gemini-test",
    )

    assert captured["video_url"] == "https://www.youtube.com/watch?v=v-url"
    assert "익선동과 북촌" in captured["prompt"]
    assert result["state"] == "done"
    assert result["places"] == 1
    assert run.state == VideoAnalysisRunState.DONE
    assert run.prompt_version == video_analysis_service.URL_SUMMARY_PROMPT_VERSION
    assert run.confidence_score == 0.88
    assert video.gemini_url_summary == "익선동 한옥거리와 북촌 산책 동선을 소개한다."
    assert video.gemini_url_summary_model == "gemini-test"
    assert video.gemini_url_summary_json["places"][0]["name"] == "익선동 한옥거리"


async def test_run_reconcile_analysis_marks_conflict_candidate_needs_review(session):
    session.add(YoutubeChannel(channel_id="UC1", title="서울여행자"))
    video = YoutubeVideo(
        video_id="v-rec",
        title="서울 시장 여행",
        url="https://www.youtube.com/watch?v=v-rec",
        channel_id="UC1",
        transcript_summary="자막에서는 광장시장과 망원시장을 언급한다.",
        gemini_url_summary_json={
            "summary": "영상에서는 광장시장 중심으로 먹거리를 소개한다.",
            "places": [{"name": "광장시장", "confidence_score": 0.9}],
        },
    )
    session.add(video)
    await session.commit()

    candidate = ExtractedPlaceCandidate(
        video_id="v-rec",
        source_text="망원시장이라고 들리는 자막 구간",
        ai_place_name="망원시장",
        match_status=MatchStatus.MATCHED,
        confidence_score=0.52,
    )
    run = YoutubeVideoAnalysisRun(
        video_id="v-rec",
        run_type=VideoAnalysisRunType.RECONCILE,
        state=VideoAnalysisRunState.PENDING,
    )
    session.add_all([candidate, run])
    await session.commit()
    await session.refresh(candidate)
    await session.refresh(run)

    def fake_llm(prompt: str) -> str:
        assert "광장시장" in prompt
        assert "망원시장" in prompt
        return json.dumps(
            {
                "summary": "URL 분석은 광장시장, 자막 후보는 망원시장이라 충돌한다.",
                "places": [
                    {
                        "name": "망원시장",
                        "decision": "conflict",
                        "transcript_candidate_ids": [candidate.id],
                        "transcript_evidence": "자막 후보",
                        "url_evidence": "URL 분석에는 광장시장만 명확함",
                        "confidence_score": 0.4,
                        "needs_review_reason": "시장명이 서로 달라 사람 검수가 필요하다.",
                    }
                ],
                "conflicts": ["시장명 충돌"],
                "overall_confidence": 0.42,
            },
            ensure_ascii=False,
        )

    result = await video_analysis_service.run_reconcile_analysis(
        session,
        video,
        run,
        llm=fake_llm,
        model="gemini-test",
    )

    assert result["state"] == "done"
    assert result["updated_review_candidates"] == 1
    assert run.state == VideoAnalysisRunState.DONE
    assert run.prompt_version == video_analysis_service.RECONCILE_PROMPT_VERSION
    assert video.reconciled_summary == "URL 분석은 광장시장, 자막 후보는 망원시장이라 충돌한다."
    assert candidate.match_status == MatchStatus.NEEDS_REVIEW
    assert candidate.analysis_run_id == run.id
    assert candidate.feature_export_status == FeatureExportStatus.PENDING
    assert candidate.review_note == "시장명이 서로 달라 사람 검수가 필요하다."
    assert candidate.provider_evidence_json["reconcile"]["analysis_run_id"] == run.id
    assert candidate.provider_evidence_json["reconcile"]["decision"] == "conflict"


async def test_make_gemini_youtube_url_llm_uses_youtube_file_data(monkeypatch):
    captured = {}

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": json.dumps(
                                        {
                                            "summary": "테스트 요약",
                                            "places": [],
                                            "overall_confidence": 0.8,
                                        },
                                        ensure_ascii=False,
                                    )
                                }
                            ]
                        }
                    }
                ]
            }

    def fake_post(url, *, headers, json, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(gemini_client.requests, "post", fake_post)

    async def fake_acquire(*, estimated_tokens, max_wait_seconds=None):
        captured["estimated_tokens"] = estimated_tokens

    # 게이트웨이 경유 확인: 멀티모달 호출도 rate limiter 예약을 거친다(T-161).
    monkeypatch.setattr(gemini_rate_limiter, "acquire", fake_acquire)

    llm = video_analysis_service.make_gemini_youtube_url_llm(
        api_key="gemini-key",
        model="gemini-3.5-flash",
        timeout_seconds=12,
    )

    payload = await llm("요약하라", "https://www.youtube.com/watch?v=abc")

    assert json.loads(payload)["summary"] == "테스트 요약"
    assert captured["headers"]["X-goog-api-key"] == "gemini-key"
    assert captured["timeout"] == 12
    assert captured["url"].endswith("/models/gemini-3.5-flash:generateContent")
    parts = captured["json"]["contents"][0]["parts"]
    assert parts[0]["file_data"]["file_uri"] == "https://www.youtube.com/watch?v=abc"
    assert parts[1]["text"] == "요약하라"
    # media part 보수적 고정 가산이 예약 추정에 포함된다(근거: llm_client 주석).
    assert captured["estimated_tokens"] >= video_analysis_service.llm_client.MULTIMODAL_MEDIA_TOKEN_SURCHARGE
    assert captured["json"]["generationConfig"]["responseMimeType"] == "application/json"
