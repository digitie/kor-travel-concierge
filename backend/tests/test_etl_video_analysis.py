"""Gemini YouTube URL 분석 서비스 테스트."""

from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import pytest
from sqlalchemy import select

from ktc.etl import gemini_client, gemini_rate_limiter, video_analysis_service
from ktc.models import (
    ExportDirtyOutbox,
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
    await session.flush()
    video = YoutubeVideo(
        video_id="v-url",
        title="서울 골목 여행",
        url="https://www.youtube.com/watch?v=v-url",
        canonical_url="https://www.youtube.com/watch?v=v-url",
        channel_id="UC1",
        channel_name="서울여행자",
        description_raw="익선동과 북촌을 걷는 영상",
    )
    session.add(video)
    await session.flush()
    run = YoutubeVideoAnalysisRun(
        video_id="v-url",
        run_type=VideoAnalysisRunType.URL_SUMMARY,
        state=VideoAnalysisRunState.PENDING,
    )
    candidate = ExtractedPlaceCandidate(
        video_id="v-url",
        source_text="익선동 후보",
        ai_place_name="익선동 한옥거리",
        match_status=MatchStatus.NEEDS_REVIEW.value,
    )
    session.add_all([run, candidate])
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
    assert result["stale_input"] is False
    assert result["places"] == 1
    assert run.state == VideoAnalysisRunState.DONE
    assert run.prompt_version == video_analysis_service.URL_SUMMARY_PROMPT_VERSION
    assert run.confidence_score == 0.88
    assert video.gemini_url_summary == "익선동 한옥거리와 북촌 산책 동선을 소개한다."
    assert video.gemini_url_summary_model == "gemini-test"
    assert video.gemini_url_summary_json["places"][0]["name"] == "익선동 한옥거리"
    assert set(
        (await session.execute(select(ExportDirtyOutbox.candidate_id))).scalars()
    ) == {candidate.id}


async def test_url_summary_does_not_apply_after_video_input_changes(
    session_factory,
):
    """외부 URL 분석 중 영상 입력이 바뀌면 stale 결과를 canonical 필드에 쓰지 않는다."""
    async with session_factory() as seed_session:
        seed_session.add(YoutubeChannel(channel_id="UC-url-stale", title="원본 채널"))
        video = YoutubeVideo(
            video_id="v-url-stale",
            title="분석 전 제목",
            url="https://youtu.be/v-url-stale",
            channel_id="UC-url-stale",
        )
        run = YoutubeVideoAnalysisRun(
            video_id=video.video_id,
            run_type=VideoAnalysisRunType.URL_SUMMARY.value,
            state=VideoAnalysisRunState.PENDING.value,
        )
        seed_session.add_all([video, run])
        await seed_session.commit()
        run_id = run.id

    llm_started = asyncio.Event()
    release_llm = asyncio.Event()

    async def paused_llm(_prompt: str, _video_url: str) -> str:
        llm_started.set()
        await release_llm.wait()
        return json.dumps(
            {
                "summary": "오래된 제목으로 만든 요약",
                "places": [],
            },
            ensure_ascii=False,
        )

    async def analyze() -> dict[str, object]:
        async with session_factory() as worker_session:
            video = await worker_session.get(YoutubeVideo, "v-url-stale")
            run = await worker_session.get(YoutubeVideoAnalysisRun, run_id)
            assert video is not None and run is not None
            return await video_analysis_service.run_url_summary_analysis(
                worker_session,
                video,
                run,
                llm=paused_llm,
                model="gemini-test",
            )

    task = asyncio.create_task(analyze())
    try:
        await asyncio.wait_for(llm_started.wait(), timeout=5)
        async with session_factory() as update_session:
            current = await update_session.get(YoutubeVideo, "v-url-stale")
            assert current is not None
            current.title = "사람이 확정한 최신 제목"
            await update_session.commit()
        release_llm.set()
        result = await asyncio.wait_for(task, timeout=5)
    finally:
        release_llm.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    assert result["state"] == VideoAnalysisRunState.RUNNING.value
    assert result["stale_input"] is True
    async with session_factory() as check_session:
        current = await check_session.get(YoutubeVideo, "v-url-stale")
        assert current is not None
        assert current.title == "사람이 확정한 최신 제목"
        assert current.gemini_url_summary is None
        assert current.gemini_url_summary_json is None


async def test_late_concurrent_url_summary_cannot_overwrite_first_canonical_result(
    session_factory,
):
    """서로 다른 pending run 중 늦은 URL 결과는 먼저 확정된 canonical을 덮지 않는다."""
    async with session_factory() as seed_session:
        seed_session.add(YoutubeChannel(channel_id="UC-url-dual", title="여행채널"))
        video = YoutubeVideo(
            video_id="v-url-dual",
            title="중복 URL 분석 영상",
            url="https://youtu.be/v-url-dual",
            channel_id="UC-url-dual",
        )
        first_run = YoutubeVideoAnalysisRun(
            video_id=video.video_id,
            run_type=VideoAnalysisRunType.URL_SUMMARY.value,
            state=VideoAnalysisRunState.PENDING.value,
        )
        second_run = YoutubeVideoAnalysisRun(
            video_id=video.video_id,
            run_type=VideoAnalysisRunType.URL_SUMMARY.value,
            state=VideoAnalysisRunState.PENDING.value,
        )
        seed_session.add_all([video, first_run, second_run])
        await seed_session.commit()
        first_run_id = first_run.id
        second_run_id = second_run.id

    first_started = asyncio.Event()
    second_started = asyncio.Event()
    release_first = asyncio.Event()
    release_second = asyncio.Event()

    async def first_llm(_prompt: str, _video_url: str) -> str:
        first_started.set()
        await release_first.wait()
        return json.dumps(
            {"summary": "먼저 확정된 URL 요약", "places": []},
            ensure_ascii=False,
        )

    async def second_llm(_prompt: str, _video_url: str) -> str:
        second_started.set()
        await release_second.wait()
        return json.dumps(
            {"summary": "늦게 도착한 URL 요약", "places": []},
            ensure_ascii=False,
        )

    async def analyze(run_id: int, llm):
        async with session_factory() as worker_session:
            video = await worker_session.get(YoutubeVideo, "v-url-dual")
            run = await worker_session.get(YoutubeVideoAnalysisRun, run_id)
            assert video is not None and run is not None
            return await video_analysis_service.run_url_summary_analysis(
                worker_session,
                video,
                run,
                llm=llm,
                model="gemini-test",
            )

    first_task = asyncio.create_task(analyze(first_run_id, first_llm))
    second_task = asyncio.create_task(analyze(second_run_id, second_llm))
    try:
        await asyncio.wait_for(
            asyncio.gather(first_started.wait(), second_started.wait()),
            timeout=5,
        )
        release_first.set()
        first_result = await asyncio.wait_for(first_task, timeout=5)
        release_second.set()
        second_result = await asyncio.wait_for(second_task, timeout=5)
    finally:
        release_first.set()
        release_second.set()
        for task in (first_task, second_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(first_task, second_task, return_exceptions=True)

    assert first_result["state"] == VideoAnalysisRunState.DONE.value
    assert first_result["stale_input"] is False
    assert second_result["state"] == VideoAnalysisRunState.FAILED.value
    assert second_result["stale_input"] is False
    assert second_result["superseded"] is True
    async with session_factory() as check_session:
        video = await check_session.get(YoutubeVideo, "v-url-dual")
        first_run = await check_session.get(YoutubeVideoAnalysisRun, first_run_id)
        second_run = await check_session.get(YoutubeVideoAnalysisRun, second_run_id)
        assert video is not None and first_run is not None and second_run is not None
        assert video.gemini_url_summary == "먼저 확정된 URL 요약"
        assert first_run.state == VideoAnalysisRunState.DONE.value
        assert first_run.summary_text == "먼저 확정된 URL 요약"
        assert second_run.state == VideoAnalysisRunState.FAILED.value
        assert second_run.summary_text == "늦게 도착한 URL 요약"
        assert second_run.last_error is not None
        assert "superseded_by_concurrent_result" in second_run.last_error


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
    assert result["stale_input"] is False
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


async def test_late_concurrent_reconcile_cannot_overwrite_first_canonical_result(
    session_factory,
):
    """같은 입력의 중복 run도 먼저 확정된 canonical reconcile 결과를 덮지 않는다."""
    async with session_factory() as seed_session:
        seed_session.add(YoutubeChannel(channel_id="UC-reconcile-dual", title="여행채널"))
        video = YoutubeVideo(
            video_id="v-reconcile-dual",
            title="중복 reconcile 영상",
            url="https://youtu.be/v-reconcile-dual",
            channel_id="UC-reconcile-dual",
            gemini_url_summary_json={"summary": "URL 기준 요약", "places": []},
        )
        first_run = YoutubeVideoAnalysisRun(
            video_id=video.video_id,
            run_type=VideoAnalysisRunType.RECONCILE.value,
            state=VideoAnalysisRunState.PENDING.value,
        )
        second_run = YoutubeVideoAnalysisRun(
            video_id=video.video_id,
            run_type=VideoAnalysisRunType.RECONCILE.value,
            state=VideoAnalysisRunState.PENDING.value,
        )
        seed_session.add_all([video, first_run, second_run])
        await seed_session.commit()
        first_run_id = first_run.id
        second_run_id = second_run.id

    first_started = asyncio.Event()
    second_started = asyncio.Event()
    release_first = asyncio.Event()
    release_second = asyncio.Event()

    async def first_llm(_prompt: str) -> str:
        first_started.set()
        await release_first.wait()
        return json.dumps(
            {"summary": "먼저 확정된 reconcile 요약", "places": [], "conflicts": []},
            ensure_ascii=False,
        )

    async def second_llm(_prompt: str) -> str:
        second_started.set()
        await release_second.wait()
        return json.dumps(
            {"summary": "늦게 도착한 reconcile 요약", "places": [], "conflicts": []},
            ensure_ascii=False,
        )

    async def analyze(run_id: int, llm):
        async with session_factory() as worker_session:
            video = await worker_session.get(YoutubeVideo, "v-reconcile-dual")
            run = await worker_session.get(YoutubeVideoAnalysisRun, run_id)
            assert video is not None and run is not None
            return await video_analysis_service.run_reconcile_analysis(
                worker_session,
                video,
                run,
                llm=llm,
                model="gemini-test",
            )

    first_task = asyncio.create_task(analyze(first_run_id, first_llm))
    second_task = asyncio.create_task(analyze(second_run_id, second_llm))
    try:
        await asyncio.wait_for(
            asyncio.gather(first_started.wait(), second_started.wait()),
            timeout=5,
        )
        release_first.set()
        first_result = await asyncio.wait_for(first_task, timeout=5)
        release_second.set()
        second_result = await asyncio.wait_for(second_task, timeout=5)
    finally:
        release_first.set()
        release_second.set()
        for task in (first_task, second_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(first_task, second_task, return_exceptions=True)

    assert first_result["state"] == VideoAnalysisRunState.DONE.value
    assert first_result["stale_input"] is False
    assert second_result["state"] == VideoAnalysisRunState.FAILED.value
    assert second_result["stale_input"] is False
    assert second_result["superseded"] is True
    async with session_factory() as check_session:
        video = await check_session.get(YoutubeVideo, "v-reconcile-dual")
        first_run = await check_session.get(YoutubeVideoAnalysisRun, first_run_id)
        second_run = await check_session.get(YoutubeVideoAnalysisRun, second_run_id)
        assert video is not None and first_run is not None and second_run is not None
        assert video.reconciled_summary == "먼저 확정된 reconcile 요약"
        assert first_run.state == VideoAnalysisRunState.DONE.value
        assert second_run.state == VideoAnalysisRunState.FAILED.value
        assert second_run.last_error is not None
        assert "superseded_by_concurrent_result" in second_run.last_error


@pytest.mark.parametrize("user_action", ["ignore", "delete"])
async def test_reconcile_preserves_concurrent_user_candidate_operation(
    session_factory,
    user_action,
):
    """LLM 대기 중의 사람 판정은 stale reconcile 결과보다 항상 우선한다."""
    from ktc.services import place_service

    async with session_factory() as seed_session:
        seed_session.add(YoutubeChannel(channel_id="UC-reconcile-race", title="검수자"))
        video = YoutubeVideo(
            video_id=f"v-reconcile-race-{user_action}",
            title="동시 검수 영상",
            url=f"https://youtu.be/reconcile-race-{user_action}",
            channel_id="UC-reconcile-race",
            transcript_summary="자막 후보 요약",
            gemini_url_summary_json={
                "summary": "URL 분석 요약",
                "places": [{"name": "동시 검수 장소"}],
            },
        )
        seed_session.add(video)
        await seed_session.flush()
        candidate = ExtractedPlaceCandidate(
            video_id=video.video_id,
            source_text="동시 검수 근거",
            ai_place_name="동시 검수 장소",
            match_status=MatchStatus.NEEDS_REVIEW,
            provider_evidence_json={
                "transcript": {"segment": "보존할 원본 근거"},
                "review": {
                    "schema_version": 1,
                    "resolutions": [
                        {
                            "resolution_id": "before-reconcile",
                            "action": "prior-review",
                        }
                    ],
                },
            },
        )
        run = YoutubeVideoAnalysisRun(
            video_id=video.video_id,
            run_type=VideoAnalysisRunType.RECONCILE,
            state=VideoAnalysisRunState.PENDING,
        )
        seed_session.add_all([candidate, run])
        await seed_session.commit()
        candidate_id = candidate.id
        run_id = run.id
        video_id = video.video_id

    llm_started = asyncio.Event()
    release_llm = asyncio.Event()

    async def paused_llm(_prompt: str) -> str:
        llm_started.set()
        await release_llm.wait()
        return json.dumps(
            {
                "summary": "사람 판정 전에 만든 stale reconcile 결과",
                "places": [
                    {
                        "name": "동시 검수 장소",
                        "decision": "conflict",
                        "transcript_candidate_ids": [candidate_id],
                        "needs_review_reason": "LLM 충돌",
                    }
                ],
                "conflicts": ["동시 판정 경합"],
            },
            ensure_ascii=False,
        )

    async def run_reconcile() -> dict[str, object]:
        async with session_factory() as worker_session:
            worker_video = await worker_session.get(YoutubeVideo, video_id)
            worker_run = await worker_session.get(YoutubeVideoAnalysisRun, run_id)
            assert worker_video is not None and worker_run is not None
            return await video_analysis_service.run_reconcile_analysis(
                worker_session,
                worker_video,
                worker_run,
                llm=paused_llm,
                model="gemini-test",
            )

    reconcile_task = asyncio.create_task(run_reconcile())
    try:
        await asyncio.wait_for(llm_started.wait(), timeout=5)
        operation_id = uuid4()
        async with session_factory() as reviewer_session:
            current = await reviewer_session.get(
                ExtractedPlaceCandidate, candidate_id
            )
            assert current is not None
            if user_action == "ignore":
                current, _, _ = await place_service.resolve_candidate(
                    reviewer_session,
                    candidate_id=candidate_id,
                    action="ignore",
                    reviewed_by="human-reviewer",
                    reviewer_type="web",
                    review_note="사람이 제외함",
                    expected_revision=current.state_revision,
                    client_operation_id=operation_id,
                )
                current, _ = (
                    await place_service.finalize_candidate_client_operation(
                        reviewer_session,
                        candidate_id=candidate_id,
                        client_operation_id=operation_id,
                        action="ignore",
                        expected_candidate_revision=current.state_revision,
                        expected_review_state=MatchStatus.IGNORED.value,
                        expected_matched_place_id=None,
                        expected_matched_place_revision=None,
                    )
                )
            else:
                await place_service.soft_delete_candidates(
                    reviewer_session,
                    [candidate_id],
                    reason="사람이 삭제함",
                    deleted_by="human-reviewer",
                    expected_status=MatchStatus.NEEDS_REVIEW,
                    expected_revisions={candidate_id: current.state_revision},
                    client_operation_id=operation_id,
                    client_operation_action="delete",
                )
                await reviewer_session.commit()
                await reviewer_session.refresh(current)
            user_revision = current.state_revision
            user_review = json.loads(
                json.dumps(current.provider_evidence_json["review"])
            )
        release_llm.set()
        result = await asyncio.wait_for(reconcile_task, timeout=5)
    finally:
        release_llm.set()
        if not reconcile_task.done():
            reconcile_task.cancel()
        await asyncio.gather(reconcile_task, return_exceptions=True)

    assert result["state"] == VideoAnalysisRunState.RUNNING.value
    assert result["stale_input"] is True
    assert result["updated_review_candidates"] == 0
    async with session_factory() as check_session:
        current = await check_session.get(ExtractedPlaceCandidate, candidate_id)
        current_run = await check_session.get(YoutubeVideoAnalysisRun, run_id)
        assert current is not None and current_run is not None
        assert current.state_revision == user_revision
        assert current.provider_evidence_json["review"] == user_review
        assert current.provider_evidence_json["review"]["last_client_operation"][
            "id"
        ] == str(operation_id)
        assert current.provider_evidence_json["transcript"] == {
            "segment": "보존할 원본 근거"
        }
        assert "reconcile" not in current.provider_evidence_json
        assert current.analysis_run_id is None
        if user_action == "ignore":
            assert current.match_status == MatchStatus.IGNORED.value
            assert current.deleted_at is None
            assert [
                item["action"]
                for item in current.provider_evidence_json["review"]["resolutions"]
            ] == ["prior-review", "ignore"]
        else:
            assert current.match_status == MatchStatus.NEEDS_REVIEW.value
            assert current.deleted_at is not None
            assert current.provider_evidence_json["review"]["resolutions"] == [
                {
                    "resolution_id": "before-reconcile",
                    "action": "prior-review",
                }
            ]
        assert current_run.state == VideoAnalysisRunState.RUNNING.value
        assert current_run.last_error is not None
        assert "stale_input" in current_run.last_error
        current_video = await check_session.get(YoutubeVideo, video_id)
        assert current_video is not None
        assert current_video.reconciled_summary is None
        assert current_video.reconciled_summary_json is None


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
