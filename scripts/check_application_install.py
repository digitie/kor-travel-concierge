"""정상 이미지의 실제 설치 버전을 소비한 constraints와 대조한다(DB/네트워크 접근 없음)."""

from __future__ import annotations

import json
import platform
import re
import subprocess
import sys
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# 기존 API/MCP 필수 축은 누락 실패를 유지한다. 전이/CS/dev catalog는 설치된 교집합만 대조한다.
REQUIRED = frozenset({
    "sqlalchemy", "asyncpg", "fastapi", "pydantic", "pydantic-core", "pydantic-settings",
    "alembic", "httpx", "uvicorn", "psycopg", "psycopg-binary",
})


def upgrade_existing_build_tools() -> None:
    """이미 설치된 두 build 도구만 정렬한다. 없는 도구는 새 설치 대상으로 만들지 않는다."""
    tools = []
    for name in ("setuptools", "wheel"):
        try:
            metadata.version(name)
        except metadata.PackageNotFoundError:
            continue
        tools.append(name)
    if tools:
        constraints = str(ROOT / "backend/application-constraints.txt")
        subprocess.run([sys.executable, "-m", "pip", "install", "--no-cache-dir", "--upgrade",
                        "-c", constraints, "--build-constraint", constraints, *tools], check=True)


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
            if name not in REQUIRED:  # CS dependency 존재는 해당 stage의 pip check/native가 별도 확인한다.
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
    return {"versions": actual, "packages": actual, "python": platform.python_version(), "commonCommit": commit}


if __name__ == "__main__":
    if sys.argv[1:] == ["--upgrade-existing-build-tools"]:
        upgrade_existing_build_tools()
    elif sys.argv[1:]:
        raise SystemExit(2)
    else:
        print(json.dumps(checked_install(), sort_keys=True))
