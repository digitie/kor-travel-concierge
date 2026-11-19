"""정상 이미지의 실제 설치 버전을 소비한 constraints와 대조한다(DB/네트워크 접근 없음)."""

from __future__ import annotations

import importlib.metadata as metadata
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def checked_install() -> dict:
    expected = dict(
        line.strip().split("==", 1)
        for line in (ROOT / "backend/application-constraints.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )
    actual = {}
    for name, wanted in expected.items():
        try:
            value = metadata.version(name)
        except metadata.PackageNotFoundError:
            if name == "psycopg2-binary":  # 기본 API/MCP에는 없고 Dagster의 pip check가 CS 존재를 보장한다.
                continue
            raise
        if value != wanted:
            raise RuntimeError(f"선택 설치 버전 불일치: {name}")
        actual[name] = value
    direct = metadata.distribution("kor-travel-common").read_text("direct_url.json")
    commit = json.loads(direct or "{}").get("vcs_info", {}).get("commit_id", "")
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise RuntimeError("실제 Common Python immutable Git metadata 없음")
    # 실제 해석 commit만 출력한다. canonical tree 동등성은 source guard/normal 증거와 함께 확인한다.
    return {"versions": actual, "commonCommit": commit}


if __name__ == "__main__":
    print(json.dumps(checked_install(), sort_keys=True))
