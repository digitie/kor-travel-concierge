"""Kor Travel Concierge MCP 도구 패키지.

외부 MCP SDK 패키지 이름도 `mcp`이므로, 프로젝트 구현은 `ktc.mcp_server`에 둔다.
`mcp/server.py`는 Docker Compose와 기존 실행 경로를 위한 얇은 호환 래퍼다.
"""

from __future__ import annotations

__all__ = ["server", "tools"]
