"""소유 user/net namespace에서 실제 TCP 단절과 보강 회복을 검증한다."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace


def namespace(kind):
    return os.readlink(f"/proc/self/ns/{kind}")


def guard_namespace(parent_net, parent_user):
    if (
        namespace("net") == parent_net
        or namespace("user") == parent_user
        or os.getuid() != 0
    ):
        raise RuntimeError("isolated user/net namespace required")
    mapping = Path("/proc/self/uid_map").read_text().split()
    if len(mapping) != 3 or mapping[0] != "0" or mapping[1] == "0" or mapping[2] != "1":
        raise RuntimeError("single non-root caller mapping required")


def run_inner(parent_net, parent_user):
    # 호스트 namespace에서는 ip/iptables 명령을 한 번도 실행하지 않는다.
    guard_namespace(parent_net, parent_user)
    subprocess.run(["ip", "link", "set", "lo", "up"], check=True)
    from ktc.etl import admin_region_service as service
    from ktc.models import TravelPlace
    from ktc.services import settings_service

    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            calls.append(self.path)
            assert self.path == "/v2/reverse"
            body = json.dumps(
                {
                    "status": "OK",
                    "candidates": [
                        {
                            "region": {
                                "sig_cd": "11680",
                                "bjd_cd": "1168010100",
                                "sido": "서울특별시",
                                "sigungu": "강남구",
                                "legal_dong": "역삼동",
                            }
                        }
                    ],
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    port = server.server_address[1]
    rule = [
        "OUTPUT",
        "-o",
        "lo",
        "-p",
        "tcp",
        "--dport",
        str(port),
        "--syn",
        "-j",
        "DROP",
    ]
    installed = False
    original_secret = settings_service.get_secret

    async def fixture_secret(_session, _key):
        return "synthetic-fixture-only"

    settings_service.get_secret = fixture_secret

    async def one():
        place = TravelPlace(
            name="격리 검증",
            latitude=37.501,
            longitude=127.036,
            sigungu_code="11110",
            sigungu_name="이전",
            is_geocoded=True,
        )
        before = (
            place.sigungu_code,
            place.sigungu_name,
            place.legal_dong_code,
            place.admin_code_geo_data_token,
        )
        started = time.monotonic()
        result = await service.enrich_place_admin_codes(
            None,
            place,
            settings=SimpleNamespace(
                KOR_TRAVEL_GEO_V2_BASE_URL=f"http://127.0.0.1:{port}"
            ),
            http_client=None,
        )
        elapsed = time.monotonic() - started
        after = (
            place.sigungu_code,
            place.sigungu_name,
            place.legal_dong_code,
            place.admin_code_geo_data_token,
        )
        return result, elapsed, before, after

    try:
        normal = asyncio.run(one())
        assert normal[0] and normal[3][0] == "11680" and len(calls) == 1
        subprocess.run(["iptables", "-A", *rule], check=True)
        installed = True
        failed = asyncio.run(one())
        counters = subprocess.check_output(
            ["iptables", "-L", "OUTPUT", "-n", "-v", "-x"], text=True
        )
        drop = [line.split() for line in counters.splitlines() if "DROP" in line]
        assert len(drop) == 1 and int(drop[0][0]) > 0
        assert failed[0] is False and failed[2] == failed[3]
        assert 1.8 <= failed[1] < 3.0, failed[1]
        assert len(calls) == 1
        subprocess.run(["iptables", "-D", *rule], check=True)
        installed = False
        recovered = asyncio.run(one())
        assert recovered[0] and recovered[3][0] == "11680" and len(calls) == 2
        return {
            "status": "PASS",
            "normal_seconds": normal[1],
            "failure_seconds": failed[1],
            "recovered_seconds": recovered[1],
            "drop_packets": int(drop[0][0]),
            "http_requests": len(calls),
            "state_preserved": True,
            "scope": "direct enrichment; real TCP SYN drop; synthetic secret lookup; no DB writes",
            "source_sha256": hashlib.sha256(
                Path(service.__file__).read_bytes()
            ).hexdigest(),
            "host_poweroff_tested": False,
            "map_mois_budget_tested": False,
        }
    finally:
        if installed:
            subprocess.run(["iptables", "-D", *rule], check=True)
        settings_service.get_secret = original_secret
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inner", nargs=2)
    args = parser.parse_args()
    if args.inner:
        print(json.dumps(run_inner(*args.inner), ensure_ascii=False))
        return
    if os.getuid() == 0:
        raise RuntimeError("launch as an unprivileged user")
    initial = (namespace("net"), namespace("user"))
    env = {k: v for k, v in os.environ.items() if "proxy" not in k.lower()}
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2] / "backend")
    child = subprocess.run(
        [
            "unshare",
            "-Urn",
            sys.executable,
            str(Path(__file__).resolve()),
            "--inner",
            *initial,
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert initial == (namespace("net"), namespace("user"))
    sys.stdout.write(child.stdout)
    sys.stderr.write(child.stderr)
    if child.returncode:
        raise SystemExit(child.returncode)


if __name__ == "__main__":
    main()
