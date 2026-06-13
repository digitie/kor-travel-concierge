"""Kor Travel Concierge CLI entrypoint."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import NoReturn


def main(argv: list[str] | None = None) -> int:
    """Run the ktcctl command."""
    parser = argparse.ArgumentParser(
        prog="ktcctl",
        description="Kor Travel Concierge 운영 CLI",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    api_parser = subparsers.add_parser("api", help="FastAPI 서버를 실행합니다.")
    api_parser.add_argument("--host", default="0.0.0.0")
    api_parser.add_argument("--port", type=int, default=12601)
    api_parser.add_argument("--reload", action="store_true")

    subparsers.add_parser("mcp", help="MCP 서버를 실행합니다.")
    subparsers.add_parser("scheduler", help="APScheduler 실행자를 실행합니다.")
    subparsers.add_parser("etl", help="ETL 샘플 파이프라인을 실행합니다.")

    args = parser.parse_args(argv)
    if args.command == "api":
        return _run_api(host=args.host, port=args.port, reload=args.reload)
    if args.command == "mcp":
        return _run_mcp()
    if args.command == "scheduler":
        return _run_scheduler()
    if args.command == "etl":
        return _run_etl()
    _unreachable(args.command)


def _run_api(*, host: str, port: int, reload: bool) -> int:
    import uvicorn

    uvicorn.run("main:app", host=host, port=port, reload=reload)
    return 0


def _run_mcp() -> int:
    from ktc.mcp_server.server import main as mcp_main

    mcp_main()
    return 0


def _run_scheduler() -> int:
    from scheduler.worker import main as scheduler_main

    scheduler_main()
    return 0


def _run_etl() -> int:
    _ensure_repo_root_on_path()
    from etl.runner import run_etl_pipeline

    run_etl_pipeline()
    return 0


def _ensure_repo_root_on_path() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    etl_dir = repo_root / "etl"
    for path in (repo_root, etl_dir):
        text = str(path)
        if text not in sys.path:
            sys.path.insert(0, text)


def _unreachable(command: str) -> NoReturn:
    raise RuntimeError(f"지원하지 않는 ktcctl command: {command}")


if __name__ == "__main__":
    raise SystemExit(main())
