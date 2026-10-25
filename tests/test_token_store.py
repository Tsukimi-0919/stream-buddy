import os
from pathlib import Path
from typing import Any

import pytest

from stream_buddy import server, token_store
from stream_buddy.__main__ import main
from stream_buddy.token_store import (
    TokenStoreError,
    default_token_dir,
    is_valid_token,
    load_or_create_token,
)


def token_file(local_app_data: Path) -> Path:
    return local_app_data / "stream-buddy" / "token"


# 保存先


def test_default_dir_is_under_local_app_data(local_app_data: Path) -> None:
    assert default_token_dir() == local_app_data / "stream-buddy"


@pytest.mark.parametrize("value", [None, ""])
def test_missing_local_app_data_is_error(
    monkeypatch: pytest.MonkeyPatch, value: str | None
) -> None:
    if value is None:
        monkeypatch.delenv("LOCALAPPDATA")
    else:
        monkeypatch.setenv("LOCALAPPDATA", value)
    with pytest.raises(TokenStoreError):
        default_token_dir()


def test_tests_do_not_use_real_local_app_data(local_app_data: Path) -> None:
    assert os.environ["LOCALAPPDATA"] == str(local_app_data)


# 作成と読み込み


def test_first_run_creates_and_saves_token(tmp_path: Path) -> None:
    token, created = load_or_create_token(tmp_path)
    assert created is True
    assert is_valid_token(token)
    assert (tmp_path / "token").read_text(encoding="ascii") == token
    # 一時ファイルは残らない
    assert [p.name for p in tmp_path.iterdir()] == ["token"]


def test_second_run_reuses_token(tmp_path: Path) -> None:
    first, _ = load_or_create_token(tmp_path)
    second, created = load_or_create_token(tmp_path)
    assert second == first
    assert created is False


def test_creates_missing_directories(tmp_path: Path) -> None:
    directory = tmp_path / "a" / "b"
    token, _ = load_or_create_token(directory)
    assert (directory / "token").read_text(encoding="ascii") == token


def test_trailing_newline_is_tolerated(tmp_path: Path) -> None:
    token, _ = load_or_create_token(tmp_path)
    (tmp_path / "token").write_text(token + "\r\n", encoding="ascii")
    assert load_or_create_token(tmp_path) == (token, False)


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"short",
        b"a" * 42,
        b"a" * 44,
        b"a" * 42 + b"!",
        b"a" * 42 + b"=",
        "あ".encode() * 15,
        b"\xff" * 43,
        b"a" * 10_000,
    ],
)
def test_broken_token_is_recreated(tmp_path: Path, content: bytes) -> None:
    (tmp_path / "token").write_bytes(content)
    token, created = load_or_create_token(tmp_path)
    assert created is True
    assert is_valid_token(token)
    assert (tmp_path / "token").read_text(encoding="ascii") == token


def test_reset_creates_new_token(tmp_path: Path) -> None:
    first, _ = load_or_create_token(tmp_path)
    second, created = load_or_create_token(tmp_path, reset=True)
    assert created is True
    assert second != first
    assert (tmp_path / "token").read_text(encoding="ascii") == second


def test_unwritable_directory_is_error_without_token(tmp_path: Path) -> None:
    # 保存先のフォルダと同じ名前のファイルがあると、フォルダを作れない
    blocker = tmp_path / "stream-buddy"
    blocker.write_text("not a directory", encoding="utf-8")
    with pytest.raises(TokenStoreError):
        load_or_create_token(blocker)


def test_failed_replace_leaves_no_temp_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*_: Any) -> None:
        raise OSError(5, "denied")

    monkeypatch.setattr(token_store.os, "replace", fail)
    with pytest.raises(TokenStoreError) as exc:
        load_or_create_token(tmp_path)
    assert list(tmp_path.iterdir()) == []
    assert "denied" in str(exc.value)


def test_tokens_are_random() -> None:
    assert token_store.new_token() != token_store.new_token()
    assert is_valid_token(token_store.new_token())


# 起動処理


@pytest.fixture
def serve_calls(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[str]:
    tokens: list[str] = []
    monkeypatch.setattr(server, "serve", lambda config, token, **kw: tokens.append(token))
    monkeypatch.chdir(tmp_path)
    return tokens


def test_main_reuses_saved_token(
    serve_calls: list[str], local_app_data: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([]) == 0
    first_out = capsys.readouterr().out
    assert main([]) == 0
    second_out = capsys.readouterr().out

    assert serve_calls[0] == serve_calls[1]
    assert token_file(local_app_data).read_text(encoding="ascii") == serve_calls[0]
    assert "新しいトークンを作りました" in first_out
    assert "新しいトークンを作りました" not in second_out
    # トークンは URL の中に1回だけ出る
    assert second_out.count(serve_calls[0]) == 1
    assert f"/overlay?token={serve_calls[0]}" in second_out


def test_main_reset_token_changes_token(
    serve_calls: list[str], local_app_data: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([]) == 0
    capsys.readouterr()
    assert main(["--reset-token"]) == 0
    out = capsys.readouterr().out

    assert serve_calls[0] != serve_calls[1]
    assert token_file(local_app_data).read_text(encoding="ascii") == serve_calls[1]
    assert "OBS の URL を設定し直してください" in out


def test_main_without_local_app_data_exits_2(
    serve_calls: list[str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("LOCALAPPDATA")
    assert main([]) == 2
    assert serve_calls == []
    assert "LOCALAPPDATA" in capsys.readouterr().err
