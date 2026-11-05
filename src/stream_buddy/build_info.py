"""ビルドの情報 (どのコミットからいつ作った exe か) を読み、`--version` の表示を作る。

情報は scripts/build_exe.py がビルドのときに作り、exe の中の stream_buddy/data/build_info.json に
同梱する。ソースの中には置かない (ソースから動かしたときは "dev")。実行時に git は呼ばない。
"""

import json
import re
from datetime import date
from importlib import resources
from importlib.resources.abc import Traversable

from stream_buddy import __version__

BUILD_INFO_NAME = "build_info.json"
DEV_LABEL = "dev"
UNKNOWN_LABEL = "unknown"
_COMMIT_PATTERN = re.compile(r"[0-9a-f]{7,40}")
_DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")


def default_source() -> Traversable:
    return resources.files("stream_buddy") / "data" / BUILD_INFO_NAME


def format_label(info: object) -> str | None:
    """ビルドの情報から「b12307a+dirty, 2026-11-05」のような表示を作る。形が違えば None。"""
    if not isinstance(info, dict) or set(info) != {"commit", "dirty", "date"}:
        return None
    commit, dirty, built = info["commit"], info["dirty"], info["date"]
    if not isinstance(commit, str) or not _COMMIT_PATTERN.fullmatch(commit):
        return None
    if not isinstance(dirty, bool) or not isinstance(built, str):
        return None
    if not _DATE_PATTERN.fullmatch(built):
        return None
    try:
        date.fromisoformat(built)
    except ValueError:
        return None
    return f"{commit}{'+dirty' if dirty else ''}, {built}"


def build_label(source: Traversable | None = None) -> str:
    """ビルドの情報がなければ "dev"、読めない・形が違えば "unknown" (エラーで止めない)。"""
    file = default_source() if source is None else source
    try:
        if not file.is_file():
            return DEV_LABEL
        info = json.loads(file.read_bytes().decode("utf-8"))
    except (OSError, ValueError):
        # UnicodeDecodeError と JSONDecodeError は ValueError の一種
        return UNKNOWN_LABEL
    return format_label(info) or UNKNOWN_LABEL


def version_text(source: Traversable | None = None) -> str:
    """`--version` の表示。例: stream-buddy 0.1.0 (b12307a, 2026-11-05)"""
    return f"stream-buddy {__version__} ({build_label(source)})"
