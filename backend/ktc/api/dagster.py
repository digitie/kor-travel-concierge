"""관리자 전용 Dagster 요약. API 프로세스는 Dagster SDK를 import하지 않는다."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends
from kortravelcommon.http import bounded_request
from pydantic import BaseModel, Field, ValidationError

from ktc.core.config import get_settings
from ktc.core.security import require_admin_proxy

router = APIRouter(prefix="/admin/dagster", dependencies=[Depends(require_admin_proxy)])
REPOSITORY = "__repository__"
RUN_FIELDS = """runId jobName status startTime endTime tags { key value }
repositoryOrigin { repositoryName repositoryLocationName }"""
QUERY = """
query ConciergeDagster($selector: RepositorySelector!, $recent: RunsFilter!, $active: RunsFilter!) {
  repositoryOrError(repositorySelector: $selector) {
    __typename
    ... on Repository {
      name location { name } pipelines { name isJob }
      schedules { name cronSchedule pipelineName executionTimezone scheduleState {
        status ticks(limit: 3, statuses: [STARTED, SKIPPED, SUCCESS, FAILURE]) { status timestamp }
      } }
      sensors { name sensorState {
        status ticks(limit: 3, statuses: [STARTED, SKIPPED, SUCCESS, FAILURE]) { status timestamp }
      } }
    }
  }
  recent: runsOrError(filter: $recent, limit: 30) { __typename ... on Runs { results { RUN_FIELDS } } }
  active: runsOrError(filter: $active, limit: 31) { __typename ... on Runs { results { RUN_FIELDS } } }
}
""".replace("RUN_FIELDS", RUN_FIELDS)


class Tick(BaseModel):
    status: str = Field(min_length=1)
    timestamp: float | None = Field(allow_inf_nan=False)


class Sensor(BaseModel):
    name: str = Field(min_length=1)
    status: str | None
    lastTick: Tick | None


class Schedule(Sensor):
    cron: str | None
    jobName: str | None
    timezone: str | None


class Repository(BaseModel):
    name: str
    locationName: str
    jobs: list[str]
    assets: list[str]
    assetCount: int
    schedules: list[Schedule]
    sensors: list[Sensor]


class Run(BaseModel):
    runId: str = Field(min_length=1)
    status: str = Field(min_length=1)
    jobName: str = Field(min_length=1)
    startTime: float | None = Field(allow_inf_nan=False)
    endTime: float | None = Field(allow_inf_nan=False)
    errorMessage: str | None = None
    maxRuntimeSeconds: int | None = None
    domainRunId: int | None = None


class Snapshot(BaseModel):
    checkedAt: str
    repositories: list[Repository]
    runs: list[Run]


class Summary(BaseModel):
    status: Literal["ok", "degraded"]
    snapshot: Snapshot | None
    error: str | None
    publicUrl: str


def tick(state):
    if (
        not isinstance(state, dict)
        or not isinstance(state.get("ticks"), list)
        or "status" not in state
    ):
        raise ValueError("sensor/schedule state 누락")
    if len(state["ticks"]) > 3:
        raise ValueError("tick 상한 초과")
    return Tick.model_validate(state["ticks"][0]) if state["ticks"] else None


def parse(payload, location):
    if (
        not isinstance(payload, dict)
        or payload.get("errors")
        or not isinstance(payload.get("data"), dict)
    ):
        raise ValueError("GraphQL 오류")
    data = payload["data"]
    repo = data.get("repositoryOrError")
    if (
        not isinstance(repo, dict)
        or repo.get("__typename") != "Repository"
        or repo.get("name") != REPOSITORY
        or repo.get("location") != {"name": location}
    ):
        raise ValueError("예상 repository/location 없음")
    for name in ("pipelines", "schedules", "sensors"):
        if not isinstance(repo.get(name), list):
            raise TypeError("필수 repository collection 누락")
    if not all(
        isinstance(p, dict)
        and isinstance(p.get("name"), str)
        and type(p.get("isJob")) is bool
        for p in repo["pipelines"]
    ):
        raise TypeError("job collection 형식 오류")
    if not all(isinstance(s, dict) for s in [*repo["schedules"], *repo["sensors"]]):
        raise TypeError("schedule/sensor collection 형식 오류")
    repository = Repository(
        name=REPOSITORY,
        locationName=location,
        jobs=[p["name"] for p in repo["pipelines"] if p["isJob"]],
        assets=[],
        assetCount=0,
        schedules=[
            Schedule(
                name=s["name"],
                status=s["scheduleState"]["status"],
                lastTick=tick(s["scheduleState"]),
                cron=s["cronSchedule"],
                jobName=s["pipelineName"],
                timezone=s["executionTimezone"],
            )
            for s in repo["schedules"]
        ],
        sensors=[
            Sensor(
                name=s["name"],
                status=s["sensorState"]["status"],
                lastTick=tick(s["sensorState"]),
            )
            for s in repo["sensors"]
        ],
    )
    merged = {}
    for key in ("active", "recent"):
        collection = data.get(key)
        if (
            not isinstance(collection, dict)
            or collection.get("__typename") != "Runs"
            or not isinstance(collection.get("results"), list)
        ):
            raise ValueError("필수 run collection 누락")
        if len(collection["results"]) > 30:
            raise ValueError("활성 실행 상한 도달: 운영 확인 필요")
        for item in collection["results"]:
            if not isinstance(item, dict):
                raise TypeError("run 형식 오류")
            if item.get("repositoryOrigin") != {
                "repositoryName": REPOSITORY,
                "repositoryLocationName": location,
            }:
                raise ValueError("run origin 불일치")
            if not isinstance(item.get("tags"), list):
                raise TypeError("run tag 누락")
            if not all(
                isinstance(t, dict)
                and isinstance(t.get("key"), str)
                and isinstance(t.get("value"), str)
                for t in item["tags"]
            ):
                raise ValueError("run tag 형식 오류")
            tags = {t["key"]: t["value"] for t in item["tags"]}
            raw_cap = tags.get("dagster/max_runtime", "")
            raw_domain = tags.get("concierge/crawl_run_id", "")
            run = Run.model_validate(
                {
                    **item,
                    "maxRuntimeSeconds": int(raw_cap)
                    if raw_cap.isascii()
                    and raw_cap.isdigit()
                    and 0 < int(raw_cap) <= 86400
                    else None,
                    "domainRunId": int(raw_domain)
                    if raw_domain.isascii()
                    and raw_domain.isdigit()
                    and 0 < int(raw_domain) <= 2147483647
                    else None,
                }
            )
            merged[run.runId] = run
    return Snapshot(
        checkedAt=datetime.now(timezone.utc).isoformat(),
        repositories=[repository],
        runs=list(merged.values()),
    )


async def fetch_summary():
    settings = get_settings()
    public = settings.KTC_DAGSTER_PUBLIC_URL.rstrip("/")
    base = settings.KTC_DAGSTER_URL.rstrip("/")
    scope = [
        {
            "key": ".dagster/repository",
            "value": f"{REPOSITORY}@{settings.KTC_DAGSTER_LOCATION}",
        }
    ]
    variables = {
        "selector": {
            "repositoryName": REPOSITORY,
            "repositoryLocationName": settings.KTC_DAGSTER_LOCATION,
        },
        "recent": {"tags": scope, "statuses": ["SUCCESS", "FAILURE", "CANCELED"]},
        "active": {
            "tags": scope,
            "statuses": ["NOT_STARTED", "QUEUED", "STARTING", "STARTED", "CANCELING"],
        },
    }
    safe_public = ""
    try:
        for url in (base, public):
            parts = urlsplit(url)
            if (
                parts.scheme not in ("http", "https")
                or not parts.hostname
                or parts.username
                or parts.password
                or parts.query
                or parts.fragment
            ):
                raise ValueError("Dagster URL 설정이 올바르지 않습니다")
        safe_public = public
        # 실패 client를 재사용하지 않는다. HTTP200 의미 오류도 degraded다.
        client = httpx.AsyncClient(timeout=5, trust_env=False)
        try:
            response = await bounded_request(
                client,
                "POST",
                base + "/graphql",
                json={"query": QUERY, "variables": variables},
            )
            response.raise_for_status()
            snapshot = parse(response.json(), settings.KTC_DAGSTER_LOCATION)
        finally:
            # response 정리와 별개로 client 종료도 bounded다. 원래 요청 취소는 보존한다.
            try:
                await asyncio.wait_for(client.aclose(), timeout=0.05)
            except Exception as exc:  # noqa: BLE001 - cleanup 오류는 정상 결과·원래 취소를 덮지 않는다
                logging.getLogger(__name__).debug(
                    "Dagster client 정리 실패(%s)", type(exc).__name__
                )
        return Summary(status="ok", snapshot=snapshot, error=None, publicUrl=public)
    except (httpx.HTTPError, ValueError, KeyError, TypeError, ValidationError) as exc:
        logging.getLogger(__name__).warning(
            "Dagster 요약 확인 실패(%s)", type(exc).__name__
        )
        return Summary(
            status="degraded",
            snapshot=None,
            error="Dagster 상태를 확인하지 못했습니다. 마지막 정상 조회를 표시합니다.",
            publicUrl=safe_public,
        )


@router.get("/summary", response_model=Summary)
async def summary():
    return await fetch_summary()
