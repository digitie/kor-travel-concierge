"""MCP 서버 엔트리포인트 (스캐폴드).

에이전트용 굵은 단위 도구 표면을 노출한다(`docs/architecture.md` 3.2, ADR-7).
세분 CRUD를 그대로 노출하지 않고, REST API와 동일한 `crawl_runs` 작업 테이블과
도메인 서비스를 공유한다.

모든 쓰기 도구는 Pydantic 스키마 검증 · 멱등 키 · 감사 로그(`audit_logs`)를
거친다. 쓰기 활성화 여부는 `MCP_WRITE_ENABLED`로 통제한다(T-011).
"""

from __future__ import annotations

from app.core.config import get_settings
from mcp.tools import READ_TOOLS, WRITE_TOOLS


def build_server():
    """MCP 서버 인스턴스를 구성한다 (T-011에서 SDK 연동).

    Placeholder: 실제 MCP SDK(`mcp` 패키지) 서버 객체에 READ_TOOLS와,
    `MCP_WRITE_ENABLED`가 켜진 경우 WRITE_TOOLS를 등록한다.
    """
    settings = get_settings()
    registered = list(READ_TOOLS)
    if settings.MCP_WRITE_ENABLED:
        registered += list(WRITE_TOOLS)
    print(
        f"[MCP] transport={settings.MCP_TRANSPORT} "
        f"write_enabled={settings.MCP_WRITE_ENABLED} "
        f"registered_tools={[t['name'] for t in registered]}"
    )
    return registered


def main() -> None:
    build_server()
    # Placeholder: transport(stdio 등)에 따라 서버 run 루프 진입.


if __name__ == "__main__":
    main()
