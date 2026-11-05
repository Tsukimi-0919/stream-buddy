"""scripts/build_exe.py のうち、PyInstaller を動かさずに確かめられるところ。"""

import importlib.util
import subprocess
import sys
from collections.abc import Callable
from datetime import date
from pathlib import Path
from types import ModuleType

import pytest

from stream_buddy import __version__

SCRIPT = Path(__file__).parent.parent / "scripts" / "build_exe.py"
FAKE_GIT = "C:/fake/git.exe"


@pytest.fixture(scope="module")
def build_exe() -> ModuleType:
    spec = importlib.util.spec_from_file_location("build_exe", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["build_exe"] = module
    spec.loader.exec_module(module)
    return module


def fake_git(outputs: dict[str, str]) -> tuple[list[list[str]], Callable[[list[str]], str]]:
    """git のサブコマンドごとの出力を返す偽物と、呼ばれた引数の記録。"""
    calls: list[list[str]] = []

    def run(args: list[str]) -> str:
        calls.append(args)
        return outputs[args[0]]

    return calls, run


def test_build_info_clean(build_exe: ModuleType) -> None:
    calls, git = fake_git({"rev-parse": "b12307a\n", "status": ""})
    info = build_exe.make_build_info(git, date(2026, 11, 5))
    assert info == {"commit": "b12307a", "dirty": False, "date": "2026-11-05"}
    assert calls == [["rev-parse", "--short", "HEAD"], ["status", "--porcelain"]]
    assert build_exe.expected_version(info) == f"stream-buddy {__version__} (b12307a, 2026-11-05)"


def test_build_info_dirty(build_exe: ModuleType) -> None:
    _, git = fake_git({"rev-parse": "b12307a\n", "status": " M src/stream_buddy/app.py\n"})
    info = build_exe.make_build_info(git, date(2026, 11, 5))
    assert info["dirty"] is True
    assert build_exe.expected_version(info).endswith("(b12307a+dirty, 2026-11-05)")


def test_build_info_fails_when_git_fails(build_exe: ModuleType) -> None:
    def git(args: list[str]) -> str:
        raise build_exe.BuildError("git が見つかりません")

    with pytest.raises(build_exe.BuildError):
        build_exe.make_build_info(git, date(2026, 11, 5))


def test_build_info_fails_when_commit_is_empty(build_exe: ModuleType) -> None:
    _, git = fake_git({"rev-parse": "\n", "status": ""})
    with pytest.raises(build_exe.BuildError):
        build_exe.make_build_info(git, date(2026, 11, 5))


def test_run_git_fails_without_git(build_exe: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(build_exe.shutil, "which", lambda name: None)
    with pytest.raises(build_exe.BuildError, match="git が見つかりません"):
        build_exe.run_git(["rev-parse", "--short", "HEAD"])


def test_run_git_fails_on_nonzero_exit(
    build_exe: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    # git はあるが、リポジトリの外などで失敗するとき
    commands: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append((command, kwargs))
        return subprocess.CompletedProcess(command, 128, "", "fatal: not a git repository")

    monkeypatch.setattr(build_exe.shutil, "which", lambda name: FAKE_GIT)
    monkeypatch.setattr(build_exe.subprocess, "run", fake_run)
    with pytest.raises(build_exe.BuildError, match="終了コード 128"):
        build_exe.run_git(["rev-parse", "--short", "HEAD"])
    command, kwargs = commands[0]
    # シェルを通さず、引数はリストで渡す
    assert command == [FAKE_GIT, "rev-parse", "--short", "HEAD"]
    assert kwargs.get("shell", False) is False


def test_run_git_fails_when_git_cannot_start(
    build_exe: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError(command[0])

    monkeypatch.setattr(build_exe.shutil, "which", lambda name: FAKE_GIT)
    monkeypatch.setattr(build_exe.subprocess, "run", fake_run)
    with pytest.raises(build_exe.BuildError):
        build_exe.run_git(["status", "--porcelain"])


def test_build_info_is_written_outside_source(build_exe: ModuleType) -> None:
    info_file = build_exe.BUILD_INFO_FILE.resolve()
    assert info_file.is_relative_to(build_exe.BUILD_ROOT.resolve())
    assert not info_file.is_relative_to(build_exe.SRC_DIR.resolve())


def test_build_info_is_bundled_as_package_data(
    build_exe: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(build_exe, "portaudio_dll", lambda: tmp_path / "portaudio.dll")
    args = build_exe.pyinstaller_args("onedir")
    assert f"{build_exe.BUILD_INFO_FILE}:stream_buddy/data" in args
