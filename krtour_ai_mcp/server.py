"""KRTour AI MCP 서버 엔트리포인트."""

from __future__ import annotations

import asyncio
from typing import Any

from app.core.config import get_settings
from app.core.database import async_session_factory, init_db
from krtour_ai_mcp.tools import ToolRuntime, register_mcp_tools, tool_metadata


def build_server(*, session_factory: Any = async_session_factory):
    """FastMCP 서버 인스턴스를 구성하고 도구를 등록한다."""
    from mcp.server.fastmcp import FastMCP

    settings = get_settings()
    server = FastMCP(
        "krtour-ai-agent",
        instructions=(
            "KRTour AI 여행 데이터베이스를 조회하고 수집, 보정, 병합, "
            "매칭 검수 작업을 수행하는 MCP 서버입니다."
        ),
        host=settings.MCP_HOST,
        port=settings.MCP_PORT,
        streamable_http_path=settings.MCP_STREAMABLE_HTTP_PATH,
    )
    runtime = ToolRuntime(
        session_factory=session_factory,
        write_enabled=settings.MCP_WRITE_ENABLED,
    )
    register_mcp_tools(server, runtime)
    return server


def registered_tool_metadata() -> list[dict[str, str]]:
    """현재 설정에서 서버가 등록하는 도구 metadata를 반환한다."""
    settings = get_settings()
    return tool_metadata(write_enabled=settings.MCP_WRITE_ENABLED)


def main() -> None:
    """DB를 초기화한 뒤 설정된 transport로 MCP 서버를 실행한다."""
    settings = get_settings()
    asyncio.run(init_db())
    server = build_server()
    server.run(transport=settings.MCP_TRANSPORT)


if __name__ == "__main__":
    main()
