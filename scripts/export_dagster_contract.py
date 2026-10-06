"""Dagster 관리자 DTO 계약을 DB 접속 없이 export/검사한다."""
import argparse
import json
from pathlib import Path

from fastapi import FastAPI
from ktc.api.dagster import router

app = FastAPI(title="Concierge Dagster admin contract", version="1")
app.include_router(router, prefix="/api/v1")
path = Path(__file__).resolve().parents[1] / "docs/contracts/dagster-summary.openapi.json"
parser = argparse.ArgumentParser()
parser.add_argument("--check", action="store_true")
args = parser.parse_args()
content = json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
if args.check:
    if not path.exists() or path.read_text() != content:
        raise SystemExit("Dagster OpenAPI export가 DTO와 다릅니다")
else:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
