"""ページと WebSocket の認証に使うトークンの保存と読み込み (ADR 0002)。

初回に作って %LOCALAPPDATA%\\stream-buddy\\token に保存し、2回目以降は使い回す。
トークンはコンソールの URL 表示以外には出さない (エラーメッセージにも含めない)。
"""

import contextlib
import os
import re
import secrets
import tempfile
from pathlib import Path

STORE_FILE_NAME = "token"
# secrets.token_urlsafe(32) の形: URL セーフな Base64 で 43 文字
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{43}")
# 読み込むのは先頭だけ (想定外に大きなファイルを丸ごと読まない)
_MAX_READ_BYTES = 256


class TokenStoreError(Exception):
    """トークンの保存先が使えないときの例外。"""


def default_token_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise TokenStoreError(
            "環境変数 LOCALAPPDATA が見つからないため、トークンの保存先を決められません"
        )
    return Path(local_app_data) / "stream-buddy"


def new_token() -> str:
    return secrets.token_urlsafe(32)


def is_valid_token(value: str) -> bool:
    return _TOKEN_PATTERN.fullmatch(value) is not None


def load_or_create_token(directory: Path, *, reset: bool = False) -> tuple[str, bool]:
    """保存済みのトークンを返す。なければ、形が違えば、reset なら作り直して保存する。

    戻り値は (トークン, 新しく作ったか)。
    """
    path = directory / STORE_FILE_NAME
    if not reset:
        saved = _read(path)
        if saved is not None and is_valid_token(saved):
            return saved, False
    token = new_token()
    _write_atomically(directory, path, token)
    return token, True


def _read(path: Path) -> str | None:
    try:
        with path.open("rb") as f:
            data = f.read(_MAX_READ_BYTES)
    except FileNotFoundError:
        return None
    except OSError as e:
        raise TokenStoreError(f"保存したトークンを読み込めません: {e.strerror}") from None
    try:
        return data.decode("ascii").strip()
    except UnicodeDecodeError:
        return None


def _write_atomically(directory: Path, path: Path, token: str) -> None:
    """一時ファイルに書いてから置き換える。途中で止まっても壊れたファイルを残さない。"""
    try:
        directory.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=directory, prefix=f"{STORE_FILE_NAME}.", suffix=".tmp")
    except OSError as e:
        raise TokenStoreError(f"トークンの保存先を用意できません: {e.strerror}") from None
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(token.encode("ascii"))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except OSError as e:
        with contextlib.suppress(OSError):
            tmp_path.unlink()
        raise TokenStoreError(f"トークンを保存できません: {e.strerror}") from None
