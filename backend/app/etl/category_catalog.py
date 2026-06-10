"""`python-krtour-map` 8자리 category 코드표 사본 로더 (T-070).

`python-krtour-map`의 `krtour.map.category`(8자리 `AABBCCDD` 코드)를 복사한
`app/data/place_category_codes.json`을 읽어, feature export의
`category_code_suggestion` 선택에 쓰는 조회/프롬프트 helper를 제공한다.

런타임에 `python-krtour-map`을 참조하면 provider↔consumer 순환참조가 되므로
코드표를 복사해 끊는다(2026-06-11 결정). 카테고리는 거의 바뀌지 않아 복사본 drift는
수용 가능하다고 판단한다. `python-krtour-map` 카테고리가 바뀌면 JSON을 재동기화한다.
`feature_id` 생성은 여전히 `python-krtour-map` 책임이다.
"""

from __future__ import annotations

import functools
import json
from pathlib import Path
from typing import Any

# 분류 미지정 루트 코드. 선택 결과가 이 코드면 "제안 없음"(None)으로 취급한다.
UNCLASSIFIED_CODE = "00000000"

_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "place_category_codes.json"


@functools.lru_cache(maxsize=1)
def _document() -> dict[str, Any]:
    with _DATA_PATH.open(encoding="utf-8") as f:
        return json.load(f)


@functools.lru_cache(maxsize=1)
def _by_code() -> dict[str, dict[str, Any]]:
    return {row["code"]: row for row in _document()["categories"]}


def iter_categories() -> list[dict[str, Any]]:
    """전체 카테고리 행을 반환한다."""
    return list(_document()["categories"])


def synced_on() -> str:
    """`python-krtour-map`에서 복사한 기준 동기화 시각."""
    return str(_document().get("_krtour_map_synced_on", ""))


def is_known_code(code: str | None) -> bool:
    """8자리 코드가 카탈로그에 존재하는지 확인한다."""
    return bool(code) and code in _by_code()


def label_for(code: str | None) -> str | None:
    """코드의 표시 label(계층 경로)을 반환한다."""
    if not code:
        return None
    row = _by_code().get(code)
    return row["label"] if row else None


def selectable_categories() -> list[dict[str, Any]]:
    """제안 후보가 될 수 있는 활성·분류 코드(루트 `00000000` 제외)."""
    return [
        row
        for row in _document()["categories"]
        if row.get("is_active", True) and row["code"] != UNCLASSIFIED_CODE
    ]


def prompt_catalog() -> str:
    """Gemini 프롬프트에 넣을 `코드\\t경로` 목록 문자열."""
    lines = [f"{row['code']}\t{row['path']}" for row in selectable_categories()]
    return "\n".join(lines)
