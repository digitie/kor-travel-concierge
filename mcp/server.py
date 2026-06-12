"""MCP 서버 호환 엔트리포인트.

외부 MCP SDK 패키지 이름도 `mcp`이므로 실제 구현은 `krtour_ai_mcp`에 둔다.
이 파일은 Docker Compose의 기존 `python /app/mcp/server.py` 명령을 보존한다.
"""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
for path in (ROOT, BACKEND):
    text = str(path)
    if text not in sys.path:
        sys.path.insert(0, text)

from krtour_ai_mcp.server import main  # noqa: E402


if __name__ == "__main__":
    main()
