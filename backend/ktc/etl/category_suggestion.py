"""Gemini로 8자리 category 코드를 고르는 선택기 (T-070).

복사한 `python-krtour-map` 카테고리 카탈로그(`category_catalog`)를 Gemini에 보여주고,
장소명·카테고리 label·설명·주소를 근거로 가장 적절한 8자리 코드 하나를 고르게 한다.
선택 결과는 카탈로그에 존재하는 코드로 검증하며, 분류 미지정(`00000000`)이나 알 수
없는 코드는 "제안 없음"(None)으로 취급한다.

실제 Gemini 호출은 주입형 `LlmCallable`(prompt -> JSON 문자열)로 분리해, 키 없이도
파싱·검증을 테스트할 수 있게 한다(`poi_extraction`과 동일 패턴). production 콜러블은
게이트웨이(`llm_client`) 경유 async이며 rate limiter 예약·thread 격리는 게이트웨이가
처리한다(T-161). 테스트 fake는 동기 함수도 지원한다.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable

from ktc.core.config import get_settings
from ktc.etl import category_catalog, llm_client

# llm 시그니처: (prompt) -> JSON 문자열 (동기 또는 awaitable)
LlmCallable = Callable[[str], "str | Awaitable[str]"]

# Gemini `response_schema`: 코드 1개 + 사유를 구조화 강제.
RESPONSE_JSON_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "category_code": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": ["category_code"],
}


def build_prompt(
    *,
    name: str,
    category_label: str | None = None,
    description: str | None = None,
    address: str | None = None,
) -> str:
    """카테고리 선택 프롬프트를 구성한다."""
    return (
        "다음 장소에 가장 적절한 카테고리 코드를 아래 목록에서 정확히 하나 고른다. "
        "목록에 없는 코드는 만들지 말고, 적절한 분류가 없으면 \"00000000\"을 고른다. "
        "반드시 주어진 JSON Schema에 맞는 JSON만 출력한다.\n\n"
        f"[장소명]\n{name}\n\n"
        f"[카테고리 힌트]\n{category_label or ''}\n\n"
        f"[설명]\n{description or ''}\n\n"
        f"[주소]\n{address or ''}\n\n"
        "[카테고리 목록] (코드<TAB>분류 경로)\n"
        f"{category_catalog.prompt_catalog()}\n"
    )


def select_category_code(payload: str) -> str | None:
    """LLM JSON 문자열을 파싱·검증해 유효한 8자리 코드만 반환한다.

    파싱 실패, 알 수 없는 코드, 분류 미지정(`00000000`)은 None.
    """
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None
    code = data.get("category_code") if isinstance(data, dict) else None
    if not isinstance(code, str):
        return None
    code = code.strip()
    if code == category_catalog.UNCLASSIFIED_CODE:
        return None
    if not category_catalog.is_known_code(code):
        return None
    return code


async def suggest_category_code(
    *,
    name: str,
    category_label: str | None = None,
    description: str | None = None,
    address: str | None = None,
    llm: LlmCallable | None,
) -> str | None:
    """Gemini로 장소의 8자리 category 코드를 제안한다.

    `llm`이 None이거나 호출/파싱이 실패하면 None을 반환한다(제안 없음). 자동 확정을
    막기 위해 불확실한 결과는 강제로 채우지 않는다.
    """
    if llm is None or not name:
        return None
    prompt = build_prompt(
        name=name,
        category_label=category_label,
        description=description,
        address=address,
    )
    try:
        payload = await llm_client.maybe_await(llm(prompt))
    except Exception:
        return None
    return select_category_code(payload)


def make_llm(runtime: llm_client.LlmRuntime) -> LlmCallable:
    """선택된 엔진(Gemini/DeepSeek) + 사전 프롬프트로 카테고리 선택 `LlmCallable`을 만든다."""

    async def call(prompt: str) -> str:
        try:
            # 카테고리 제안은 best-effort(null 허용)이므로 단발 호출만 한다. 느린
            # 사람-유사 재시도(15~90s)를 타면 대화형 호출부(검수 저장·harvest)가
            # 오래 기다리므로, max_attempts=1로 빠르게 실패한다.
            return await llm_client.complete_json(
                runtime,
                prompt,
                response_schema=RESPONSE_JSON_SCHEMA,
                max_attempts=1,
            )
        except llm_client.LlmRequestError as exc:
            raise RuntimeError(
                f"카테고리 제안 호출 실패(status={exc.status_code}, model={runtime.model})"
            ) from exc

    return call


def make_gemini_category_llm(
    *,
    api_key: str | None = None,
    model: str | None = None,
    timeout_seconds: float = 30.0,
) -> LlmCallable:
    """`.env`/인자 기반 production `LlmCallable` (BACK-COMPAT shim → make_llm)."""
    from dataclasses import replace

    runtime = llm_client.LlmRuntime.from_settings(model=model)
    if api_key:
        runtime = replace(runtime, gemini_api_key=api_key)
    if not (runtime.gemini_api_key or runtime.is_deepseek):
        raise ValueError("GEMINI_API_KEY가 필요하다")
    return make_llm(runtime)


def default_category_llm() -> LlmCallable | None:
    """설정에 Gemini 키가 있으면 production caller, 없으면 None을 반환한다.

    키가 없는 로컬/테스트에서는 None이라 카테고리 제안을 건너뛴다.
    """
    if not get_settings().GEMINI_API_KEY:
        return None
    return make_gemini_category_llm()


# 장소 컨텍스트로 8자리 코드를 고르는 selector. services 계층(예: place_service)이
# etl을 직접 import하지 않고 주입받아 쓰도록 callable로 노출한다(async — 게이트웨이 경유).
CategoryCodeSelector = Callable[..., "Awaitable[str | None]"]


def make_default_selector() -> CategoryCodeSelector | None:
    """설정 기반 기본 카테고리 코드 selector를 만든다.

    Gemini 키가 없으면 None(제안 비활성). 반환 callable은
    `(name, category_label, description, address)` 키워드로 호출한다.
    """
    llm = default_category_llm()
    if llm is None:
        return None

    async def selector(
        *,
        name: str,
        category_label: str | None = None,
        description: str | None = None,
        address: str | None = None,
    ) -> str | None:
        return await suggest_category_code(
            name=name,
            category_label=category_label,
            description=description,
            address=address,
            llm=llm,
        )

    return selector
