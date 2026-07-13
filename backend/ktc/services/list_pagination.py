"""목록 API의 공통 keyset cursor와 응답 구조.

cursor는 첫 페이지의 최신 ID를 snapshot watermark로 보존한다. 다음 페이지는 이
watermark 이하만 조회하므로 페이지를 넘기는 동안 더 큰 ID가 추가돼도 기존 순회에
끼어들지 않는다. 새 행 수는 별도 `newer_than_id` count로 계산한다.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar("T")

_CURSOR_VERSION = 1
CURSOR_MAX_LENGTH = 4096
MAX_DB_INTEGER_ID = 2_147_483_647


@dataclass(frozen=True)
class DecodedCursor:
    """검증을 마친 목록 cursor."""

    snapshot_id: int
    keys: tuple[Any, ...]


@dataclass(frozen=True)
class ListPage(Generic[T]):
    """검수·작업·장소·테마 목록의 공통 응답."""

    items: list[T]
    next_cursor: str | None
    has_more: bool
    total: int
    newest_id: int | None
    newer_than: int


async def ensure_repeatable_read(session: AsyncSession) -> None:
    """한 목록 응답 안의 여러 SELECT를 같은 PostgreSQL snapshot에 묶는다.

    API 목록 session은 조회 전에 비어 있으므로 `REPEATABLE READ` connection을 먼저
    획득한다. 이미 transaction을 시작한 내부 호출자는 해당 transaction 경계를 존중한다.
    """
    if not session.in_transaction():
        await session.connection(
            execution_options={"isolation_level": "REPEATABLE READ"}
        )


def filter_fingerprint(
    *, scope: str, sort: str, filters: dict[str, Any]
) -> str:
    """cursor를 endpoint·정렬·filter 조합에 묶는 짧은 fingerprint."""
    canonical = json.dumps(
        {"scope": scope, "sort": sort, "filters": filters},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()[:32]


def encode_cursor(
    *, fingerprint: str, snapshot_id: int, keys: tuple[Any, ...]
) -> str:
    """목록 cursor를 URL-safe opaque 문자열로 만든다."""
    payload = json.dumps(
        {
            "v": _CURSOR_VERSION,
            "f": fingerprint,
            "w": snapshot_id,
            "k": list(keys),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_cursor(
    cursor: str, *, fingerprint: str, key_count: int
) -> DecodedCursor:
    """cursor 구조와 현재 filter fingerprint를 검증한다."""
    try:
        padding = "=" * (-len(cursor) % 4)
        raw = base64.b64decode(
            (cursor + padding).encode("ascii"), altchars=b"-_", validate=True
        )
        payload = json.loads(raw.decode("utf-8"))
    except (
        binascii.Error,
        RecursionError,
        UnicodeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        raise ValueError("유효하지 않은 목록 cursor입니다") from exc

    if not isinstance(payload, dict) or set(payload) != {"v", "f", "w", "k"}:
        raise ValueError("유효하지 않은 목록 cursor입니다")
    candidate_fingerprint = payload["f"]
    if (
        type(payload["v"]) is not int
        or payload["v"] != _CURSOR_VERSION
        or not isinstance(candidate_fingerprint, str)
        or len(candidate_fingerprint) != 32
        or any(char not in "0123456789abcdef" for char in candidate_fingerprint)
        or not hmac.compare_digest(candidate_fingerprint, fingerprint)
    ):
        raise ValueError("현재 정렬 또는 필터에 사용할 수 없는 목록 cursor입니다")
    if (
        not isinstance(payload["w"], int)
        or isinstance(payload["w"], bool)
        or payload["w"] < 0
        or payload["w"] > MAX_DB_INTEGER_ID
        or not isinstance(payload["k"], list)
        or len(payload["k"]) != key_count
    ):
        raise ValueError("유효하지 않은 목록 cursor입니다")
    return DecodedCursor(snapshot_id=payload["w"], keys=tuple(payload["k"]))


def page_payload(page: ListPage[dict[str, Any]]) -> dict[str, Any]:
    """공통 REST envelope로 직렬화한다."""
    return {
        "items": page.items,
        "next_cursor": page.next_cursor,
        "has_more": page.has_more,
        "total": page.total,
        "newest_id": page.newest_id,
        "newer_than": page.newer_than,
    }
