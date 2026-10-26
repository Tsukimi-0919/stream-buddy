"""状態機械のパッケージ全体の決まりを確かめる。"""

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = ROOT / "src" / "stream_buddy" / "state"
TESTS_DIR = Path(__file__).resolve().parent
SPEC = ROOT / "docs" / "state-machine.md"

FORBIDDEN = ["time", "random", "asyncio", "sounddevice", "fastapi"]


def test_state_package_has_no_forbidden_imports() -> None:
    pattern = re.compile(
        r"^\s*(?:import|from)\s+(" + "|".join(FORBIDDEN) + r")(?:\.|\s|$)", re.MULTILINE
    )
    files = sorted(STATE_DIR.glob("*.py"))
    assert files
    for path in files:
        found = pattern.findall(path.read_text(encoding="utf-8"))
        assert found == [], f"{path.name} が {found} を import している"


def test_every_transition_id_has_a_test() -> None:
    ids = sorted(set(re.findall(r"ST-(\d{2})", SPEC.read_text(encoding="utf-8"))))
    assert len(ids) == 14  # ST-01〜04、ST-11〜15、ST-21〜25

    names: list[str] = []
    for path in TESTS_DIR.glob("test_*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names += [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    covered = {m for name in names for m in re.findall(r"(?<![a-z0-9])st(\d{2})(?!\d)", name)}
    missing = [f"ST-{i}" for i in ids if i not in covered]
    assert missing == [], f"テストのない遷移: {missing}"
