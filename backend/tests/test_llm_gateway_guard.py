"""direct SDK guard — LLM 게이트웨이(T-161) 우회 회귀 방지.

`backend/ktc` + 리포 루트 `scheduler/`·`mcp/`·`etl/` 소스를 스캔해
allowlist(`gemini_client.py`, `deepseek_client.py`, `llm_client.py`,
`gemini_rate_limiter.py`) 밖에서 다음을 검출하면 실패한다:

(a) `google.genai`/`genai.` 직접 사용 및 `openai` SDK import (provider SDK 직접 호출)
(b) `post_generate_content`/`post_chat_completion(_payload)` 직접 호출
    (Gemini/DeepSeek HTTP 헬퍼 우회)
(c) `gemini_rate_limiter.acquire` 직접 호출 (게이트웨이 밖 이중 quota 예약)

새 LLM 호출부는 반드시 `llm_client`(complete_json/complete_text/generate_multimodal)를
경유해야 한다 — quota reservation·thread 격리·usage 실측이 게이트웨이 한 곳에 있다.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
KTC_ROOT = REPO_ROOT / "backend" / "ktc"

# 스캔 루트 — backend 패키지 + LLM 호출이 유입될 수 있는 리포 루트 실행 계층.
# (없는 디렉터리는 건너뛴다 — 레이아웃 변화에 유연하게.)
SCAN_ROOTS: tuple[Path, ...] = (
    KTC_ROOT,
    REPO_ROOT / "scheduler",
    REPO_ROOT / "mcp",
    REPO_ROOT / "etl",
)

# 게이트웨이 구현 계층 — provider HTTP 헬퍼·rate limiter를 직접 다룰 수 있는 유일한 파일들.
ALLOWLIST = frozenset(
    {
        "gemini_client.py",
        "deepseek_client.py",
        "llm_client.py",
        "gemini_rate_limiter.py",
    }
)

# (사유, 패턴) — 소스 원문(주석/독스트링 포함) 기준 검출. 문서 언급도 남기지 않아
# 우회 예제가 복사되는 것을 막는다.
_BANNED_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "google-genai SDK 직접 사용 금지 (게이트웨이 llm_client 경유)",
        re.compile(
            r"\bgoogle\.genai\b|\bgenai\.|from\s+google\s+import\s+[^\n]*\bgenai\b|import\s+genai\b"
        ),
    ),
    (
        "openai SDK 직접 사용 금지 (DeepSeek는 게이트웨이 llm_client 경유)",
        re.compile(r"\bimport\s+openai\b|\bfrom\s+openai\b"),
    ),
    (
        "gemini_client.post_generate_content 직접 호출 금지 (게이트웨이 llm_client 경유)",
        re.compile(r"\bpost_generate_content\b"),
    ),
    (
        "deepseek_client.post_chat_completion(_payload) 직접 호출 금지 (게이트웨이 llm_client 경유)",
        re.compile(r"\bpost_chat_completion(_payload)?\b"),
    ),
    (
        "gemini_rate_limiter.acquire 직접 호출 금지 (게이트웨이 밖 이중 quota 예약)",
        re.compile(
            r"gemini_rate_limiter\s*\.\s*acquire"
            r"|from\s+ktc\.etl\.gemini_rate_limiter\s+import\s+[^\n]*\bacquire\b"
        ),
    ),
]


def scan_source(text: str, *, label: str) -> list[str]:
    """소스 문자열에서 금지 패턴을 찾아 `파일:라인 사유` 목록을 반환한다."""
    violations: list[str] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        for reason, pattern in _BANNED_PATTERNS:
            if pattern.search(line):
                violations.append(f"{label}:{line_no} {reason} — {line.strip()}")
    return violations


def find_violations(root: Path) -> list[str]:
    """`root` 아래 모든 .py에서 allowlist 밖 금지 패턴 사용을 수집한다."""
    violations: list[str] = []
    for path in sorted(root.rglob("*.py")):
        if path.name in ALLOWLIST:
            continue
        label = path.relative_to(REPO_ROOT).as_posix()
        violations.extend(scan_source(path.read_text(encoding="utf-8"), label=label))
    return violations


def test_no_direct_sdk_usage_outside_gateway():
    assert KTC_ROOT.is_dir(), f"ktc 소스 루트가 없다: {KTC_ROOT}"
    violations: list[str] = []
    for root in SCAN_ROOTS:
        if root.is_dir():
            violations.extend(find_violations(root))
    assert violations == [], (
        "LLM 게이트웨이(T-161) 우회 감지 — llm_client 경유로 이관하라:\n"
        + "\n".join(violations)
    )


def test_guard_detects_violations_in_source_text():
    """guard 자기 검증 — 일부러 위반 코드 문자열을 넣으면 전부 잡아야 한다."""
    offending = (
        "from google import genai\n"
        "client = genai.Client()\n"
        "import openai\n"
        "data = gemini_client.post_generate_content(api_key=k, model=m, body={})\n"
        "text = deepseek_client.post_chat_completion(api_key=k, model=m, prompt=p)\n"
        "payload = deepseek_client.post_chat_completion_payload(api_key=k, model=m, prompt=p)\n"
        "await gemini_rate_limiter.acquire(estimated_tokens=1)\n"
        "from ktc.etl.gemini_rate_limiter import acquire\n"
    )
    violations = scan_source(offending, label="fake_module.py")
    reasons = "\n".join(violations)
    assert "genai" in reasons
    assert "openai" in reasons
    assert "post_generate_content" in reasons
    assert "post_chat_completion" in reasons
    assert "이중 quota 예약" in reasons
    # 8줄 전부 최소 1건씩 검출된다.
    assert len(violations) >= 8

    # 정상 코드(게이트웨이 경유)는 검출하지 않는다.
    clean = (
        "from ktc.etl import llm_client\n"
        "text = await llm_client.complete_json(runtime, prompt)\n"
        "tok = gemini_rate_limiter.estimate_tokens(prompt)\n"
        "raise llm_client.GeminiQuotaBusy('busy')\n"
    )
    assert scan_source(clean, label="clean_module.py") == []


def test_allowlist_files_exist():
    """allowlist 파일명이 실제 게이트웨이 구현과 함께 이동/개명되면 guard를 갱신하도록 고정."""
    etl = KTC_ROOT / "etl"
    for name in ALLOWLIST:
        assert (etl / name).is_file(), f"allowlist 파일이 없다(개명/이동 시 guard 갱신): {name}"
