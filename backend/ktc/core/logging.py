"""로깅 유틸리티.

API 키와 접근 키를 로그에 평문으로 남기지 않기 위한 마스킹 헬퍼를 제공한다.
(`AGENTS.md` DO NOT 2: API 키 평문 커밋·출력 금지)
"""

from __future__ import annotations


def mask_secret(value: str | None, *, visible: int = 4) -> str:
    """민감 문자열의 끝 일부만 남기고 마스킹한다.

    예: `mask_secret("AIzaSyABCDEF1234")` -> `"************1234"`
    """
    if not value:
        return ""
    if len(value) <= visible:
        return "*" * len(value)
    return "*" * (len(value) - visible) + value[-visible:]
