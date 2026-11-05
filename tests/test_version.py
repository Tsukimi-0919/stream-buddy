import json
import tomllib
from pathlib import Path

import pytest

from stream_buddy import __version__, build_info
from stream_buddy.__main__ import main

PACKAGE_DIR = Path(__file__).parent.parent / "src" / "stream_buddy"


def test_version_matches_pyproject() -> None:
    pyproject = Path(__file__).parent.parent / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    assert data["project"]["version"] == __version__


def test_main_prints_dev_version_from_source(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"stream-buddy {__version__} (dev)"


def test_build_info_is_not_in_source() -> None:
    # ビルドの情報は build/ に書き、exe にだけ同梱する (コミットに混ざらない)
    assert list(PACKAGE_DIR.rglob(build_info.BUILD_INFO_NAME)) == []


def write_info(tmp_path: Path, content: object) -> Path:
    path = tmp_path / build_info.BUILD_INFO_NAME
    path.write_text(json.dumps(content), encoding="utf-8")
    return path


def test_version_without_build_info_is_dev(tmp_path: Path) -> None:
    missing = tmp_path / build_info.BUILD_INFO_NAME
    assert build_info.version_text(missing) == f"stream-buddy {__version__} (dev)"


def test_version_with_build_info(tmp_path: Path) -> None:
    path = write_info(tmp_path, {"commit": "b12307a", "dirty": False, "date": "2026-11-05"})
    assert build_info.version_text(path) == f"stream-buddy {__version__} (b12307a, 2026-11-05)"


def test_version_with_dirty_build(tmp_path: Path) -> None:
    path = write_info(tmp_path, {"commit": "b12307a", "dirty": True, "date": "2026-11-05"})
    assert (
        build_info.version_text(path) == f"stream-buddy {__version__} (b12307a+dirty, 2026-11-05)"
    )


@pytest.mark.parametrize(
    "content",
    [
        [],
        "b12307a",
        {"commit": "b12307a", "dirty": False},
        {"commit": "b12307a", "dirty": False, "date": "2026-11-05", "extra": 1},
        {"commit": "B12307A", "dirty": False, "date": "2026-11-05"},
        {"commit": "abc", "dirty": False, "date": "2026-11-05"},
        {"commit": "b12307a; x", "dirty": False, "date": "2026-11-05"},
        {"commit": 12307, "dirty": False, "date": "2026-11-05"},
        {"commit": "b12307a", "dirty": "no", "date": "2026-11-05"},
        {"commit": "b12307a", "dirty": 0, "date": "2026-11-05"},
        {"commit": "b12307a", "dirty": False, "date": "2026-13-45"},
        {"commit": "b12307a", "dirty": False, "date": "20261105"},
        {"commit": "b12307a", "dirty": False, "date": None},
    ],
)
def test_version_with_unexpected_build_info_is_unknown(tmp_path: Path, content: object) -> None:
    path = write_info(tmp_path, content)
    assert build_info.version_text(path) == f"stream-buddy {__version__} (unknown)"


@pytest.mark.parametrize("data", [b"{not json", b"\xff\xfe", b""])
def test_version_with_broken_build_info_is_unknown(tmp_path: Path, data: bytes) -> None:
    path = tmp_path / build_info.BUILD_INFO_NAME
    path.write_bytes(data)
    assert build_info.version_text(path) == f"stream-buddy {__version__} (unknown)"


def test_main_prints_version_from_build_info(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # exe の中と同じく、stream_buddy/data/build_info.json があるときの表示
    path = write_info(tmp_path, {"commit": "0123abcd", "dirty": False, "date": "2026-11-05"})
    monkeypatch.setattr(build_info, "default_source", lambda: path)
    with pytest.raises(SystemExit):
        main(["--version"])
    assert capsys.readouterr().out.strip() == f"stream-buddy {__version__} (0123abcd, 2026-11-05)"


def test_version_does_not_run_git() -> None:
    # 実行時は同梱したファイルを読むだけで、git を呼ばない
    source = (PACKAGE_DIR / "build_info.py").read_text(encoding="utf-8")
    assert "subprocess" not in source
