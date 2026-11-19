"""실제 MCP 2 서버의 도구 schema·쓰기 gate·transport 경계. DB/외부 HTTP 없음."""

import json
from importlib import metadata
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from ktc.mcp_server import server as module

BASELINE = json.loads((Path(__file__).parent / "fixtures/mcp130-tool-schema.json").read_text())


def settings(transport="streamable-http", write=False):
    return SimpleNamespace(MCP_WRITE_ENABLED=write, MCP_TRANSPORT=transport,
                           MCP_HOST="127.0.0.1", MCP_PORT=17777,
                           MCP_STREAMABLE_HTTP_PATH="/rpc-test")


@pytest.mark.parametrize("write", [False, True])
async def test_real_mcp2_tools_match_actual_mcp130_input_schemas(monkeypatch, write):
    def no_db():
        raise AssertionError("schema 검사에서 DB session을 열면 안 된다")
    monkeypatch.setattr(module, "get_settings", lambda: settings(write=write))
    server = module.build_server(session_factory=no_db)
    actual = [{key: tool.model_dump(by_alias=True).get(key)
               for key in ("name", "description", "inputSchema")}
              for tool in await server.list_tools()]
    assert actual == BASELINE[str(write)]
    assert len(actual) == (9 if write else 3)
    assert metadata.version("mcp") == "2.3.0"
    assert metadata.version("mcp-types") == "2.3.0"


@pytest.mark.parametrize("transport,options", [
    ("stdio", {}),
    ("sse", {"host": "127.0.0.1", "port": 17777}),
    ("streamable-http", {"host": "127.0.0.1", "port": 17777,
                          "streamable_http_path": "/rpc-test"}),
])
def test_main_preserves_real_transport_settings_without_socket_or_db(monkeypatch, transport, options):
    calls = []
    async def no_db_init():
        calls.append("init")
    server = SimpleNamespace(run=Mock())
    monkeypatch.setattr(module, "get_settings", lambda: settings(transport=transport))
    monkeypatch.setattr(module, "init_db", no_db_init)
    monkeypatch.setattr(module, "build_server", lambda: server)
    module.main()
    assert calls == ["init"]
    server.run.assert_called_once_with(transport=transport, **options)


def test_rest_gateway_has_no_unused_google_sdk_installation():
    for name in ("google-generativeai", "google-ai-generativelanguage"):
        with pytest.raises(metadata.PackageNotFoundError):
            metadata.version(name)


async def test_real_mcp2_asgi_initialization_and_readonly_tool_list(monkeypatch):
    import httpx2
    protocol = BASELINE["protocolVersion"]  # 실제 이전 SDK의 client protocol 경계를 고정한다.

    def no_db():
        raise AssertionError("metadata RPC에서 DB session을 열면 안 된다")
    async def status_without_db(self, *, job_id):
        return {"job_id": job_id, "status": "succeeded"}
    monkeypatch.setattr(module.ToolRuntime, "get_harvest_status", status_without_db)
    monkeypatch.setattr(module, "get_settings", lambda: settings(write=False))
    server = module.build_server(session_factory=no_db)
    app = server.streamable_http_app(streamable_http_path="/rpc-test", json_response=True,
                                    stateless_http=True, host="127.0.0.1")
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://127.0.0.1:17777") as client,
    ):
        headers = {"Accept": "application/json, text/event-stream"}
        rejected = await client.post("/rpc-test", headers={**headers, "Host": "untrusted.example:17777"},
                                     json={"jsonrpc": "2.0", "id": 0, "method": "tools/list"})
        assert rejected.status_code == 421
        response = await client.post("/rpc-test", headers=headers, json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": protocol, "capabilities": {},
                "clientInfo": {"name": "offline-contract", "version": "1"},
            },
        })
        assert response.status_code == 200
        assert response.json()["result"]["protocolVersion"] == protocol
        headers["MCP-Protocol-Version"] = protocol
        response = await client.post("/rpc-test", headers=headers,
                                     json={"jsonrpc": "2.0", "method": "notifications/initialized"})
        assert response.status_code == 202
        response = await client.post("/rpc-test", headers=headers,
                                     json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        assert response.status_code == 200
        actual = [{key: tool.get(key) for key in ("name", "description", "inputSchema")}
                  for tool in response.json()["result"]["tools"]]
        assert actual == BASELINE["False"]
        response = await client.post("/rpc-test", headers=headers, json={
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "get_harvest_status", "arguments": {"job_id": 42}},
        })
        assert response.status_code == 200
        result = response.json()["result"]
        expected = {"job_id": 42, "status": "succeeded"}
        assert result["isError"] is False
        assert result["structuredContent"] == expected
        assert json.loads(result["content"][0]["text"]) == expected
