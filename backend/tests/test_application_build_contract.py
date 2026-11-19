"""실제 Docker 설치 입력과 설치본 readback 계약. DB/앱 import는 필요 없다."""

from __future__ import annotations

from contextlib import ExitStack
import importlib.util
import json
from pathlib import Path
import re
import shlex
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
CONSTRAINTS = "/app/backend/application-constraints.txt"
READBACK = "/app/scripts/check_application_install.py"


def assert_install_bindings(dockerfile: str) -> None:
    """주석이 아닌 실제 RUN 두 개의 설치/검사 순서와 stage별 소비를 검증한다."""
    continued = re.sub(r"\\\s*\n\s*", " ", dockerfile)
    instructions = [
        line.strip()
        for line in continued.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    copies = {
        target: instructions.index(f"COPY {source} {target}")
        for source, target in (
            ("backend/application-constraints.txt", CONSTRAINTS),
            ("scripts/check_application_install.py", READBACK),
        )
    }
    assert "FROM python:3.12-slim AS runtime" in instructions, "실제 역할 Python3.12 경계가 필요하다"
    bootstrap = [(index, shlex.split(line[4:])) for index, line in enumerate(instructions)
                 if line.startswith("RUN python -m pip install ")]
    assert len(bootstrap) == 1, "실제 pip bootstrap 하나가 필요하다"
    bootstrap_index, bootstrap_tokens = bootstrap[0]
    bootstrap_pip = bootstrap_tokens[:bootstrap_tokens.index("&&")]
    assert "-c" in bootstrap_pip and bootstrap_pip[bootstrap_pip.index("-c") + 1] == CONSTRAINTS
    assert bootstrap_pip[-1] == "pip" and not {"setuptools", "wheel"} & set(bootstrap_pip), "미사용 build 도구를 강제하지 않는다"
    assert "--upgrade-existing-build-tools" in bootstrap_tokens
    stage = instructions.index("FROM runtime AS dagster")
    installs = [
        (index, shlex.split(line[4:]))
        for index, line in enumerate(instructions)
        if line.startswith("RUN pip install ")
    ]
    assert len(installs) == 2, "runtime/CS의 실제 설치 RUN 두 개가 필요하다"
    assert installs[0][0] < stage < installs[1][0], "stage별 설치 경계가 다르다"
    for index, tokens in installs:
        assert all(copy < index for copy in copies.values()), "설치 전 COPY가 필요하다"
        assert all(copy < bootstrap_index < index for copy in copies.values()), "constraints COPY 뒤 bootstrap, 그 뒤 앱 설치가 필요하다"
        separator = tokens.index("&&")
        pip = tokens[:separator]
        assert "-c" in pip and pip[pip.index("-c") + 1] == CONSTRAINTS
        assert "--build-constraint" in pip and pip[pip.index("--build-constraint") + 1] == CONSTRAINTS
        assert not any(
            token == "-r" and pip[position + 1] == CONSTRAINTS
            for position, token in enumerate(pip[:-1])
        ), "constraints를 requirements로 설치하면 미사용 패키지를 강제한다"
        post = tokens[separator:]
        assert post[:8] == [
            "&&", "python", "-m", "pip", "check", "&&", "python", READBACK
        ], "정상 설치 직후 pip check와 실제 설치본 readback이 필요하다"
    runtime = installs[0][1]
    for manifest in (
        "backend/requirements.txt", "etl/requirements.txt",
        "scheduler/requirements.txt", "mcp/requirements.txt",
    ):
        assert manifest in runtime, "기존 공유 이미지의 설치 범위를 보존한다"
    assert "/app/dagster/requirements.txt" in installs[1][1]


class DockerBindingTests(unittest.TestCase):
    def test_actual_normal_dockerfile(self):
        assert_install_bindings((ROOT / "Dockerfile.python").read_text())

    def test_removed_or_misbound_real_inputs_fail(self):
        original = (ROOT / "Dockerfile.python").read_text()
        constraint = f"-c {CONSTRAINTS}"
        mutations = {
            "bootstrap_unbound": original.replace(constraint, "", 1),
            "runtime_unbound": original.replace(f"--build-constraint {CONSTRAINTS} {constraint}", f"--build-constraint {CONSTRAINTS}", 1),
            "build_unbound": original.replace(f"--build-constraint {CONSTRAINTS}", ""),
            "bootstrap_commented": original.replace("RUN python -m pip install", "# RUN python -m pip install"),
            "unused_build_tools_forced": original.replace("constraints.txt pip", "constraints.txt pip setuptools wheel", 1),
            "cs_unbound": original.rsplit(constraint, 1)[0] + original.rsplit(constraint, 1)[1],
            "force_install_unused": original.replace(constraint, f"-r {CONSTRAINTS}"),
            "relative_cs_path": original.replace(constraint, "-c backend/application-constraints.txt"),
            "missing_pip_check": original.replace("&& python -m pip check", ""),
            "missing_readback": original.replace(f"&& python {READBACK}", ""),
            "comment_not_command": original.replace("RUN pip install", "# RUN pip install"),
            "late_copy": original.replace(
                f"COPY backend/application-constraints.txt {CONSTRAINTS}\n", ""
            ) + f"\nCOPY backend/application-constraints.txt {CONSTRAINTS}\n",
        }
        for name, mutated in mutations.items():
            with self.subTest(name=name), self.assertRaises((AssertionError, ValueError)):
                assert_install_bindings(mutated)


class InstalledReadbackTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location(
            "application_install_contract", ROOT / "scripts/check_application_install.py"
        )
        self.helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.helper)
        self.versions = dict(
            line.split("==", 1)
            for line in (ROOT / "backend/application-constraints.txt").read_text().splitlines()
            if line and not line.startswith("#")
        )

    def readback(self, versions, commit="c289b4624c8640eb918cc915803e72ae754e58fb"):
        def installed(name):
            if name not in versions:
                raise self.helper.metadata.PackageNotFoundError(name)
            return versions[name]

        with ExitStack() as stack:
            stack.enter_context(patch.object(self.helper.metadata, "version", side_effect=installed))
            dist = stack.enter_context(patch.object(self.helper.metadata, "distribution"))
            dist.return_value.read_text.return_value = json.dumps({"vcs_info": {"commit_id": commit}})
            return self.helper.checked_install()

    def test_api_without_unused_psycopg2(self):
        versions = {name: self.versions[name] for name in self.helper.REQUIRED}
        versions.update({name: self.versions[name] for name in ("anyio", "starlette", "pyproj")})
        self.assertEqual(self.readback(versions)["versions"], versions)

    def test_cs_with_existing_storage_driver(self):
        self.assertEqual(self.readback(self.versions)["versions"], self.versions)

    def test_old_or_missing_installed_versions_rejected(self):
        for name in ("sqlalchemy", "pydantic-core", "psycopg-binary", "psycopg2-binary"):
            with self.subTest(old=name), self.assertRaises(RuntimeError):
                self.readback({**self.versions, name: "0.0.1"})
        for name in ("sqlalchemy", "pydantic-core", "psycopg", "asyncpg"):
            with self.subTest(missing=name), self.assertRaises(self.helper.metadata.PackageNotFoundError):
                self.readback({key: value for key, value in self.versions.items() if key != name})

    def test_old_shared_transitives_rejected_without_installing_unused_members(self):
        for name in ("anyio", "starlette", "filelock", "protobuf", "pyproj"):
            with self.subTest(package=name), self.assertRaises(RuntimeError):
                self.readback({**self.versions, name: "0.0.1"})

    def test_readback_has_actual_python_and_installed_intersection_cli_shape(self):
        versions = {name: self.versions[name] for name in self.helper.REQUIRED}
        with patch.object(self.helper.platform, "python_version", return_value="3.11.18"):
            result = self.readback(versions)
        self.assertEqual(result["python"], "3.11.18")
        self.assertEqual(result["packages"], versions)
        self.assertEqual(result["versions"], versions)
        self.assertNotIn("dagster", result["packages"])
        self.assertNotIn("ruff", result["packages"])

    def test_missing_build_tools_are_not_installed(self):
        with patch.object(self.helper.metadata, "version", side_effect=self.helper.metadata.PackageNotFoundError), \
                patch.object(self.helper.subprocess, "run") as child:
            self.helper.upgrade_existing_build_tools()
        child.assert_not_called()

    def test_existing_build_tool_only_and_child_failure_is_preserved(self):
        def installed(name):
            if name == "setuptools":
                return "79.0.1"
            raise self.helper.metadata.PackageNotFoundError(name)
        with patch.object(self.helper.metadata, "version", side_effect=installed), \
                patch.object(self.helper.subprocess, "run") as child:
            self.helper.upgrade_existing_build_tools()
            command = child.call_args.args[0]
            self.assertEqual(command[-1], "setuptools")
            self.assertNotIn("wheel", command)
            self.assertIn("--build-constraint", command)
            self.assertTrue(child.call_args.kwargs["check"])
            child.side_effect = self.helper.subprocess.CalledProcessError(1, command)
            with self.assertRaises(self.helper.subprocess.CalledProcessError):
                self.helper.upgrade_existing_build_tools()

    def test_common_immutable_provenance_required(self):
        for value in ("", "main", "c289b462", None):
            with self.subTest(commit=value), self.assertRaises(RuntimeError):
                self.readback(self.versions, commit=value)


if __name__ == "__main__":
    unittest.main()
