"""GitHub Actions のワークフローで、Action がコミットハッシュで固定され、そろっていること (T-18)。

Dependabot が一部のファイルだけを更新し、同じ Action のハッシュがずれたことがあったため。
ワークフローのファイルは読むだけで、変更しない。
"""

import re
from collections import defaultdict
from pathlib import Path

import pytest

WORKFLOW_DIR = Path(__file__).parent.parent / ".github" / "workflows"
# "- uses: owner/repo@ref # v1.2.3" や "uses: owner/repo/path@ref" の形
USES_RE = re.compile(r"^\s*(?:-\s+)?uses:\s*['\"]?([^\s'\"#]+)['\"]?", re.MULTILINE)
SHA_RE = re.compile(r"[0-9a-f]{40}")
NOT_PINNED = "が 40 文字のコミットハッシュで固定されていません"


def workflow_files() -> list[Path]:
    return sorted([*WORKFLOW_DIR.glob("*.yml"), *WORKFLOW_DIR.glob("*.yaml")])


def find_uses(text: str) -> list[tuple[int, str]]:
    """(行番号, uses の値) の一覧。"""
    return [(text.count("\n", 0, m.start()) + 1, m.group(1)) for m in USES_RE.finditer(text)]


def collect_uses() -> list[tuple[str, int, str]]:
    """(ファイル名, 行番号, uses の値) の一覧。リポジトリ内の Action (./) は除く。"""
    found = []
    for path in workflow_files():
        for line, value in find_uses(path.read_text(encoding="utf-8")):
            if not value.startswith("./"):
                found.append((path.name, line, value))
    return found


def unpinned(uses: list[tuple[str, int, str]]) -> list[str]:
    problems = []
    for name, line, value in uses:
        _, sep, ref = value.partition("@")
        if not sep or not SHA_RE.fullmatch(ref):
            problems.append(f"{name}:{line} {value} {NOT_PINNED}")
    return problems


def mismatched(uses: list[tuple[str, int, str]]) -> list[str]:
    refs: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for name, line, value in uses:
        action, _, ref = value.partition("@")
        refs[action][ref].append(f"{name}:{line}")
    problems = []
    for action, by_ref in sorted(refs.items()):
        if len(by_ref) > 1:
            places = "、".join(
                f"{ref}（{', '.join(where)}）" for ref, where in sorted(by_ref.items())
            )
            problems.append(f"{action} のハッシュがそろっていません: {places}")
    return problems


def test_workflow_files_exist() -> None:
    assert workflow_files(), f"{WORKFLOW_DIR} にワークフローがありません"
    assert collect_uses(), "uses: が見つかりません (読み取りの正規表現を確かめてください)"


def test_all_actions_are_pinned_to_commit_sha() -> None:
    problems = unpinned(collect_uses())
    assert not problems, "\n".join(problems)


def test_same_action_uses_same_sha() -> None:
    problems = mismatched(collect_uses())
    assert not problems, "\n".join(problems)


# --- 確かめる仕組みそのもののテスト ---

SHA_A = "a" * 40
SHA_B = "b" * 40


def test_find_uses_reads_both_forms() -> None:
    text = (
        "steps:\n"
        f"  - uses: actions/checkout@{SHA_A} # v7\n"
        "  - name: x\n"
        f"    uses: 'actions/attest-build-provenance@{SHA_B}'\n"
    )
    assert find_uses(text) == [
        (2, f"actions/checkout@{SHA_A}"),
        (4, f"actions/attest-build-provenance@{SHA_B}"),
    ]


@pytest.mark.parametrize(
    "value",
    ["actions/checkout@v4", "actions/checkout@main", "actions/checkout", f"a/b@{SHA_A[:39]}"],
)
def test_unpinned_detects_tags_and_branches(value: str) -> None:
    problems = unpinned([("ci.yml", 3, value)])
    assert problems == [f"ci.yml:3 {value} {NOT_PINNED}"]


def test_mismatched_names_files_and_action() -> None:
    uses = [
        ("ci.yml", 10, f"astral-sh/setup-uv@{SHA_A}"),
        ("release.yml", 20, f"astral-sh/setup-uv@{SHA_B}"),
        ("ci.yml", 5, f"actions/checkout@{SHA_A}"),
        ("release.yml", 6, f"actions/checkout@{SHA_A}"),
    ]
    problems = mismatched(uses)
    assert len(problems) == 1
    assert "astral-sh/setup-uv" in problems[0]
    assert "ci.yml:10" in problems[0]
    assert "release.yml:20" in problems[0]
