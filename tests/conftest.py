from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def local_app_data(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """すべてのテストで LOCALAPPDATA を一時フォルダに差し替え、実際の場所には書かない。"""
    path = tmp_path_factory.mktemp("localappdata")
    monkeypatch.setenv("LOCALAPPDATA", str(path))
    return path
