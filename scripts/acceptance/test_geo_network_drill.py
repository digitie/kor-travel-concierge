"""격리 guard와 실제 단절 효과. Linux의 명시적 수용 명령으로 실행한다."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).with_name("geo_network_drill.py")
spec = importlib.util.spec_from_file_location("drill", SCRIPT)
drill = importlib.util.module_from_spec(spec)
spec.loader.exec_module(drill)


@pytest.mark.parametrize(
    "net_same,user_same", [(True, False), (False, True), (True, True)]
)
def test_same_namespace_rejected_before_network_commands(
    monkeypatch, net_same, user_same
):
    monkeypatch.setattr(drill, "namespace", lambda kind: kind)
    monkeypatch.setattr(
        drill.subprocess,
        "run",
        lambda *a, **kw: pytest.fail("network command before guard"),
    )
    with pytest.raises(RuntimeError, match="namespace required"):
        drill.run_inner(
            "net" if net_same else "other-net", "user" if user_same else "other-user"
        )


def test_actual_syn_drop_and_recovery():
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        timeout=40,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["status"] == "PASS"
    assert 1.8 <= data["failure_seconds"] < 3.0
    assert data["drop_packets"] > 0 and data["http_requests"] == 2
    assert data["state_preserved"]
