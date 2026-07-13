from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


_ROOT = Path(__file__).resolve().parents[2]
_VERSIONS_DIR = _ROOT / "backend" / "alembic" / "versions"


def _revision_id(path: Path) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(target, ast.Name) and target.id == "revision" for target in node.targets):
            value = ast.literal_eval(node.value)
            if isinstance(value, str):
                return value
    raise AssertionError(f"revision 선언을 찾을 수 없습니다: {path.name}")


def test_alembic_revision_ids_are_unique_and_graph_has_single_head() -> None:
    paths_by_revision: defaultdict[str, list[str]] = defaultdict(list)
    for path in sorted(_VERSIONS_DIR.glob("*.py")):
        if path.name == "__init__.py":
            continue
        paths_by_revision[_revision_id(path)].append(path.name)

    duplicates = {
        revision: paths
        for revision, paths in paths_by_revision.items()
        if len(paths) > 1
    }
    assert duplicates == {}

    config = Config(str(_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_ROOT / "backend" / "alembic"))
    assert len(ScriptDirectory.from_config(config).get_heads()) == 1
