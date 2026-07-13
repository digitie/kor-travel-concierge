"""장소 단위 Gemini Deep Research 실행 서비스.

`trigger_deep_research`가 만든 `deep_research` 작업을 scheduler가 실제로 처리할 수
있도록, 장소 상세 조사 프롬프트 구성, Gemini 호출, 결과 파싱, DB 반영을 한 곳에
모은다. 테스트에서는 `llm`을 주입해 외부 API 없이 검증한다.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ktc.etl import llm_client
from ktc.models import TravelPlace
from ktc.services import feature_export_service, settings_service

# llm 시그니처: (prompt) -> JSON 문자열 (동기 또는 awaitable — production은
# 게이트웨이 경유 async, 테스트 fake는 동기 지원).
LlmCallable = Callable[[str], "str | Awaitable[str]"]
StatusReporter = Callable[[str, float | None], Awaitable[None]]
GEMINI_API_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


class DeepResearchError(RuntimeError):
    """Deep Research 결과를 생성하거나 파싱하지 못한 경우."""


class DeepResearchResult(BaseModel):
    """Gemini Deep Research 구조화 결과."""

    detailed_research_content: str = ""
    gemini_enriched_description: str | None = None
    source_notes: list[str] = Field(default_factory=list)


RESPONSE_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "detailed_research_content": {"type": "string"},
        "gemini_enriched_description": {"type": "string"},
        "source_notes": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["detailed_research_content"],
}


async def _report(
    status_reporter: StatusReporter | None,
    message: str,
    progress: float | None = None,
) -> None:
    if status_reporter is not None:
        await status_reporter(message, progress)


def _compact(value: str | None) -> str:
    return " ".join(value.split()) if value else ""


def build_prompt(
    place: TravelPlace,
    *,
    prompt: str | None,
    max_sources: int,
) -> str:
    """장소 상세 조사를 위한 Gemini 프롬프트를 구성한다."""
    context = {
        "name": place.name,
        "category": place.category,
        "official_address": place.official_address,
        "road_address": place.road_address,
        "latitude": place.latitude,
        "longitude": place.longitude,
        "description": place.description,
        "gemini_enriched_description": place.gemini_enriched_description,
    }
    return (
        "다음 여행지 정보를 바탕으로 사용자가 여행 계획에 바로 활용할 수 있는 "
        "심층 소개를 한국어로 작성하라. 과장된 단정은 피하고, 근거가 불확실한 "
        "내용은 source_notes에 주의점으로 남겨라. "
        "반드시 주어진 JSON Schema에 맞는 JSON만 출력하라.\n\n"
        f"[장소 정보]\n{json.dumps(context, ensure_ascii=False)}\n\n"
        f"[사용자 추가 지시]\n{_compact(prompt) or '추가 지시 없음'}\n\n"
        f"[참고 출처 상한]\n최대 {max_sources}개 관점으로 정리\n"
    )


def parse_deep_research(payload: str) -> DeepResearchResult:
    """LLM JSON 문자열을 파싱·검증한다."""
    try:
        data = json.loads(payload)
        result = DeepResearchResult.model_validate(data)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise DeepResearchError(f"Deep Research 결과 파싱 실패: {exc}") from exc
    if not result.detailed_research_content.strip():
        raise DeepResearchError("Deep Research 결과가 비어 있다")
    return result


def make_llm(runtime: llm_client.LlmRuntime) -> LlmCallable:
    """선택된 엔진(Gemini/DeepSeek) + 사전 프롬프트로 Deep Research `LlmCallable`을 만든다."""

    async def call(prompt: str) -> str:
        try:
            return await llm_client.complete_json(
                runtime, prompt, response_schema=RESPONSE_JSON_SCHEMA
            )
        except llm_client.LlmRequestError as exc:
            raise DeepResearchError(
                "Deep Research 호출 실패"
                f"(status={exc.status_code}, model={runtime.model})"
            ) from exc

    return call


def make_gemini_llm(
    *,
    api_key: str | None = None,
    model: str | None = None,
    timeout_seconds: float = 60.0,
) -> LlmCallable:
    """`.env`/인자 기반 production `LlmCallable` (BACK-COMPAT shim → make_llm)."""
    from dataclasses import replace

    runtime = llm_client.LlmRuntime.from_settings(model=model)
    if api_key:
        runtime = replace(runtime, gemini_api_key=api_key)
    if not (runtime.gemini_api_key or runtime.is_deepseek):
        raise ValueError("GEMINI_API_KEY가 필요하다")
    return make_llm(runtime)


async def research_place(
    session: AsyncSession,
    place: TravelPlace,
    *,
    prompt: str | None = None,
    max_sources: int = 8,
    llm: LlmCallable | None = None,
    status_reporter: StatusReporter | None = None,
) -> dict[str, Any]:
    """장소 1건의 Deep Research를 실행하고 최신 입력일 때만 결과를 저장한다.

    외부 LLM을 기다리는 동안 DB transaction이나 place row lock을 잡지 않는다. 대신
    prompt를 만든 시점의 ``state_revision``과 완성된 prompt를 snapshot으로 보존하고,
    응답 뒤 export lock -> place row 순서로 최신 행을 잠가 둘 다 그대로인지 확인한다.
    그 사이 사람 보정 등 다른 writer가 장소를 바꿨다면 LLM 결과를 폐기하고
    ``status=stale_input``/``applied=False``를 반환한다.
    """
    place_id = place.place_id
    if place_id is None:
        raise ValueError("Deep Research 대상 place_id가 필요하다")

    await _report(
        status_reporter,
        f"{place.name} Deep Research 프롬프트를 구성했습니다.",
        0.25,
    )
    runtime = await settings_service.get_llm_runtime(session)
    resolved_llm = llm or make_llm(runtime)
    # 호출자가 넘긴 ORM instance가 같은 session identity map에서 오래됐을 수 있으므로,
    # prompt/revision snapshot은 DB 최신 행을 populate_existing으로 다시 읽어 만든다.
    snapshot_place = (
        await session.execute(
            select(TravelPlace)
            .where(TravelPlace.place_id == place_id)
            .execution_options(populate_existing=True, autoflush=False)
        )
    ).scalar_one_or_none()
    if snapshot_place is None:
        await session.commit()
        raise ValueError(f"place not found: {place_id}")
    snapshot_revision = snapshot_place.state_revision
    snapshot_name = snapshot_place.name
    request_prompt = build_prompt(
        snapshot_place,
        prompt=prompt,
        max_sources=max_sources,
    )

    # snapshot SELECT가 연 transaction/connection을 외부 LLM 대기 전에 반환한다.
    await session.commit()

    await _report(
        status_reporter,
        f"Gemini에서 {snapshot_name} 상세 조사를 실행 중입니다.",
        0.45,
    )
    # thread 격리·rate limiter 예약은 게이트웨이(`llm_client`)가 처리한다(T-161).
    raw_result = await llm_client.maybe_await(resolved_llm(request_prompt))
    result = parse_deep_research(raw_result)

    # dirty sync와 같은 export -> place 잠금 순서를 사용한다. 최신 revision이나 prompt
    # 입력이 하나라도 달라졌으면, 사람/다른 worker의 결과를 stale AI가 덮지 않는다.
    await feature_export_service.acquire_feature_export_lock(session)
    current_place = (
        await session.execute(
            select(TravelPlace)
            .where(TravelPlace.place_id == place_id)
            .with_for_update()
            .execution_options(populate_existing=True, autoflush=False)
        )
    ).scalar_one_or_none()
    current_revision = (
        current_place.state_revision if current_place is not None else None
    )
    stale_input = (
        current_place is None
        or current_revision != snapshot_revision
        or build_prompt(
            current_place,
            prompt=prompt,
            max_sources=max_sources,
        )
        != request_prompt
    )
    if stale_input:
        await session.commit()
        await _report(
            status_reporter,
            f"{snapshot_name} 정보가 조사 중 변경되어 Deep Research 결과를 적용하지 않았습니다.",
            0.8,
        )
        return {
            "place_id": place_id,
            "place_name": snapshot_name,
            "status": "stale_input",
            "stale_input": True,
            "applied": False,
            "expected_state_revision": snapshot_revision,
            "current_state_revision": current_revision,
        }

    assert current_place is not None
    enriched_description = result.gemini_enriched_description
    detailed_changed = (
        current_place.detailed_research_content
        != result.detailed_research_content
    )
    enriched_changed = bool(enriched_description) and (
        current_place.gemini_enriched_description != enriched_description
    )
    content_changed = detailed_changed or enriched_changed
    if detailed_changed:
        current_place.detailed_research_content = result.detailed_research_content
    if enriched_changed:
        current_place.gemini_enriched_description = enriched_description
    current_place.last_reviewed_at = datetime.now(timezone.utc)
    if content_changed:
        # 한 장소에 co-match된 READY 후보의 place block이 모두 같은 최신 설명을 보도록
        # 실제 결과 변경과 dirty 표시를 같은 transaction에 묶는다.
        await feature_export_service.mark_place_candidates_dirty(
            session,
            current_place.place_id,
            reason="deep_research",
        )
    await session.commit()

    await _report(
        status_reporter,
        f"{current_place.name} Deep Research 결과를 저장했습니다.",
        0.8,
    )
    return {
        "place_id": current_place.place_id,
        "place_name": current_place.name,
        "status": "researched",
        "stale_input": False,
        "applied": True,
        "changed": content_changed,
        "detailed_research_content": result.detailed_research_content,
        "gemini_enriched_description": result.gemini_enriched_description,
        "source_notes": result.source_notes,
    }
