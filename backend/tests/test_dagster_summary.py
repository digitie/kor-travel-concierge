"""공용 Dagster 요약의 범위·실패·인증 계약."""

import copy
import json

import httpx
import pytest
from ktc.api import dagster as api
from ktc.core.config import Settings, get_settings
from ktc.core.security import ADMIN_ACTOR_HEADER_NAME, ADMIN_PROXY_SECRET_HEADER_NAME
from main import app

LOCATION = "ktc.dagster.definitions"


def payload():
    return {
        "data": {
            "repositoryOrError": {
                "__typename": "Repository",
                "name": "__repository__",
                "location": {"name": LOCATION},
                "pipelines": [{"name": "concierge_batch", "isJob": True}],
                "schedules": [],
                "sensors": [
                    {
                        "name": "concierge_dispatch",
                        "sensorState": {
                            "status": "RUNNING",
                            "ticks": [{"status": "SKIPPED", "timestamp": 42}],
                        },
                    }
                ],
            },
            "recent": {
                "__typename": "Runs",
                "results": [
                    {
                        "runId": "native-1",
                        "jobName": "concierge_batch",
                        "status": "FAILURE",
                        "startTime": 1,
                        "endTime": 2,
                        "repositoryOrigin": {
                            "repositoryName": "__repository__",
                            "repositoryLocationName": LOCATION,
                        },
                        "tags": [{"key": "concierge/crawl_run_id", "value": "17"}],
                    }
                ],
            },
            "active": {"__typename": "Runs", "results": []},
        }
    }


def test_tick_and_runtime_are_observed_without_inventing_a_cap():
    result = api.parse(payload(), LOCATION)
    assert result.repositories[0].sensors[0].lastTick.status == "SKIPPED"
    assert result.runs[0].domainRunId == 17
    assert result.runs[0].maxRuntimeSeconds is None
    data = payload()
    data["data"]["recent"]["results"][0]["tags"].append(
        {"key": "dagster/max_runtime", "value": "60"}
    )
    assert api.parse(data, LOCATION).runs[0].maxRuntimeSeconds == 60


@pytest.mark.parametrize(
    "defect",
    [
        "foreign",
        "errors",
        "null-run",
        "nan",
        "tick-overflow",
        "bad-job",
        "missing-active",
        "overflow-active",
    ],
)
def test_malformed_or_foreign_snapshot_is_rejected(defect):
    data = payload()
    row = data["data"]["recent"]["results"][0]
    if defect == "foreign":
        row["repositoryOrigin"]["repositoryLocationName"] = "foreign"
    elif defect == "errors":
        data["errors"] = [{"message": "private upstream details"}]
    elif defect == "null-run":
        data["data"]["recent"]["results"] = [None]
    elif defect == "nan":
        row["startTime"] = float("nan")
    elif defect == "tick-overflow":
        data["data"]["repositoryOrError"]["sensors"][0]["sensorState"]["ticks"] *= 4
    elif defect == "bad-job":
        data["data"]["repositoryOrError"]["pipelines"] = [None]
    elif defect == "missing-active":
        del data["data"]["active"]
    elif defect == "overflow-active":
        data["data"]["active"]["results"] = [copy.deepcopy(row) for _ in range(31)]
    with pytest.raises((ValueError, TypeError)):
        api.parse(data, LOCATION)


@pytest.mark.asyncio
async def test_bounded_named_query_and_http200_errors_are_degraded(monkeypatch):
    received = []
    original = httpx.AsyncClient

    def upstream(request):
        received.append(json.loads(request.content))
        return httpx.Response(200, json={"errors": [{"message": "private detail"}]})

    monkeypatch.setattr(
        api.httpx,
        "AsyncClient",
        lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(upstream)),
    )
    monkeypatch.setattr(api, "get_settings", lambda: Settings())
    result = await api.fetch_summary()
    assert result.status == "degraded" and result.snapshot is None
    assert "private detail" not in result.error
    variables = received[0]["variables"]
    assert variables["active"]["tags"] == [
        {"key": ".dagster/repository", "value": "__repository__@" + LOCATION}
    ]
    assert set(variables["active"]["statuses"]) == {
        "NOT_STARTED",
        "QUEUED",
        "STARTING",
        "STARTED",
        "CANCELING",
    }
    assert "statuses: [STARTED, SKIPPED, SUCCESS, FAILURE]" in received[0]["query"]
    assert "limit: 3" in received[0]["query"]


@pytest.mark.asyncio
async def test_admin_secret_is_required_even_with_local_api_auth(monkeypatch):
    settings = Settings(APP_ENV="local", KTC_ADMIN_PROXY_SECRET="test-only-" + "x" * 32)
    app.dependency_overrides[get_settings] = lambda: settings

    async def summary():
        return api.Summary(
            status="ok", snapshot=None, error=None, publicUrl="http://localhost"
        )

    monkeypatch.setattr(api, "fetch_summary", summary)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            assert (
                await client.get("/api/v1/admin/dagster/summary")
            ).status_code == 403
            forged = {
                ADMIN_ACTOR_HEADER_NAME: "admin",
                ADMIN_PROXY_SECRET_HEADER_NAME: "forged",
            }
            assert (
                await client.get("/api/v1/admin/dagster/summary", headers=forged)
            ).status_code == 403
            valid = {
                ADMIN_ACTOR_HEADER_NAME: "admin",
                ADMIN_PROXY_SECRET_HEADER_NAME: settings.KTC_ADMIN_PROXY_SECRET,
            }
            assert (
                await client.get("/api/v1/admin/dagster/summary", headers=valid)
            ).status_code == 200
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_slow_client_close_does_not_hold_a_valid_summary(monkeypatch):
    import asyncio

    original = httpx.AsyncClient

    class SlowClose(httpx.MockTransport):
        async def aclose(self):
            await asyncio.sleep(60)

    transport = SlowClose(lambda request: httpx.Response(200, json=payload()))
    monkeypatch.setattr(
        api.httpx,
        "AsyncClient",
        lambda **kwargs: original(**kwargs, transport=transport),
    )
    monkeypatch.setattr(api, "get_settings", lambda: Settings())
    result = await asyncio.wait_for(api.fetch_summary(), timeout=0.5)
    assert result.status == "ok"


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_cleanup_oserror_preserves_valid_result_or_original_cancel(
    monkeypatch, cancel
):
    import asyncio

    original = httpx.AsyncClient

    class BadClose(httpx.MockTransport):
        async def aclose(self):
            raise OSError("isolated cleanup failure")

    def request(req):
        if cancel:
            raise asyncio.CancelledError("original cancellation")
        return httpx.Response(200, json=payload())

    monkeypatch.setattr(
        api.httpx,
        "AsyncClient",
        lambda **kwargs: original(**kwargs, transport=BadClose(request)),
    )
    monkeypatch.setattr(api, "get_settings", lambda: Settings())
    if cancel:
        with pytest.raises(asyncio.CancelledError, match="original cancellation"):
            await api.fetch_summary()
    else:
        assert (await api.fetch_summary()).status == "ok"
