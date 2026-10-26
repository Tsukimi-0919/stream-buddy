"""セリフ集 (TOML) の読み込みと検証、場面に合わせたセリフの選択 (FR-06、NFR-04)。

既定のセリフ集は data/lines.toml。exe の中でも見つかるよう importlib.resources で読む。
エラーメッセージにはセリフの本文もファイルのパスも出さず、どのセリフかは何番目かで示す。
"""

import random
import tomllib
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path, PureWindowsPath

from stream_buddy.config import ConfigError
from stream_buddy.protocol import MAX_SAY_TEXT_LENGTH
from stream_buddy.state.events import Situation, TensionLevel

# 表とキー。7 つのリストはすべて必須
SCHEMA: dict[str, tuple[str, ...]] = {
    "silence": ("calm", "normal", "high"),
    "tension": ("high",),
    "event": ("death", "clear"),
}
MAX_FILE_BYTES = 64 * 1024
MAX_LINES_PER_LIST = 30
# 制御文字 (Cc・Cf) のうち、絵文字に使うので許すもの: ゼロ幅接合子、異体字セレクタ
ALLOWED_FORMAT_CHARS = frozenset({"‍", "️"})

type ListKey = tuple[str, str]


class LinesError(ConfigError):
    """セリフ集が読めない、または内容が正しくないときの例外。"""


@dataclass(frozen=True)
class LineBook:
    """検証済みのセリフ集。(表, キー) ごとのセリフのリスト。"""

    lists: Mapping[ListKey, tuple[str, ...]]

    def get(self, table: str, key: str) -> tuple[str, ...]:
        return self.lists[(table, key)]


def load_lines(file: str = "") -> LineBook:
    """セリフ集を読み込んで検証する。file が空文字なら既定のセリフ集。

    指定したファイルが読めない・正しくないときは、既定に戻さず LinesError にする。
    """
    if file:
        if not PureWindowsPath(file).is_absolute():
            raise LinesError(
                "[lines] file は絶対パスで指定してください（空文字なら既定のセリフ集）"
            )
        data = _read_file(Path(file))
        where = "[lines] file のセリフ集"
    else:
        data = (resources.files("stream_buddy") / "data" / "lines.toml").read_bytes()
        where = "既定のセリフ集"
    if len(data) > MAX_FILE_BYTES:
        raise LinesError(f"{where}が大きすぎます（上限 {MAX_FILE_BYTES // 1024} KB）")
    try:
        parsed = tomllib.loads(data.decode("utf-8"))
    except UnicodeDecodeError:
        raise LinesError(f"{where}は UTF-8 で保存してください") from None
    except tomllib.TOMLDecodeError as e:
        raise LinesError(f"{where}が TOML として正しくありません: {e}") from None
    errors, book = _validate(parsed)
    if errors:
        raise LinesError(f"{where}に誤りがあります:\n" + "\n".join(errors))
    return book


def _read_file(path: Path) -> bytes:
    try:
        with path.open("rb") as f:
            # 上限を超えたかがわかるよう、1 バイト多く読む
            return f.read(MAX_FILE_BYTES + 1)
    except OSError as e:
        # パスには個人のフォルダ名が入りうるので出さない
        raise LinesError(f"[lines] file のセリフ集を読み込めません: {e.strerror}") from None


def _validate(data: dict[str, object]) -> tuple[list[str], LineBook]:
    errors: list[str] = []
    lists: dict[ListKey, tuple[str, ...]] = {}
    for table in data:
        if table not in SCHEMA:
            errors.append(f"[{table}] は知らない表です（書き間違いがないか確認してください）")
    for table, keys in SCHEMA.items():
        section = data.get(table)
        if section is None:
            errors.append(f"[{table}] がありません")
            continue
        if not isinstance(section, dict):
            errors.append(f"[{table}] は表（[{table}]）で書いてください")
            continue
        for key in section:
            if key not in keys:
                errors.append(
                    f"[{table}] {key} は知らない項目です（書き間違いがないか確認してください）"
                )
        for key in keys:
            where = f"[{table}] {key}"
            if key not in section:
                errors.append(f"{where} がありません")
                continue
            lines = section[key]
            if not isinstance(lines, list):
                errors.append(f"{where} は配列（[...]）で書いてください")
                continue
            if not 1 <= len(lines) <= MAX_LINES_PER_LIST:
                errors.append(
                    f"{where} のセリフが {len(lines)} 個です"
                    f"（1〜{MAX_LINES_PER_LIST} 個にしてください）"
                )
            for index, line in enumerate(lines, start=1):
                problem = _check_line(line)
                if problem:
                    errors.append(f"{where} の {index} 番目{problem}")
            lists[(table, key)] = tuple(line for line in lines if isinstance(line, str))
    return errors, LineBook(lists)


def _check_line(line: object) -> str | None:
    """問題があれば、その説明 (「の N 番目」に続く文) を返す。"""
    if not isinstance(line, str):
        return 'が文字列ではありません（"..." で書いてください）'
    if not line.strip():
        return "が空です（空白だけのセリフは使えません）"
    if len(line) > MAX_SAY_TEXT_LENGTH:
        return f"が {len(line)} 文字です（上限 {MAX_SAY_TEXT_LENGTH} 文字）"
    for ch in line:
        if ch in "\n\r" or unicodedata.category(ch) in ("Zl", "Zp"):
            return "に改行が含まれています"
        if ch == "\t":
            return "にタブが含まれています"
        if unicodedata.category(ch) in ("Cc", "Cf") and ch not in ALLOWED_FORMAT_CHARS:
            return f"に制御文字（U+{ord(ch):04X}）が含まれています"
    return None


def line_id(table: str, key: str, index: int) -> str:
    """say の line_id。「表.キー.番号」で、番号は 1 から (エラーメッセージの「N 番目」と同じ)。"""
    return f"{table}.{key}.{index + 1}"


def list_for(situation: Situation, tension: TensionLevel) -> ListKey:
    """Say の場面から、使うリストの (表, キー) を決める。"""
    match situation:
        case "silence":
            return ("silence", tension)
        case "high":
            return ("tension", "high")
        case "death" | "clear":
            return ("event", situation)


@dataclass
class LinePicker:
    """場面とテンションに合わせてセリフを選ぶ。同じリストの直前のセリフは選ばない。"""

    book: LineBook
    rng: random.Random = field(default_factory=random.Random)
    _last: dict[ListKey, int] = field(default_factory=dict, init=False, repr=False)

    def pick(self, situation: Situation, tension: TensionLevel) -> tuple[str, str]:
        """(line_id, text) を返す。"""
        table, key = list_for(situation, tension)
        lines = self.book.get(table, key)
        candidates = [i for i in range(len(lines)) if i != self._last.get((table, key))]
        index = self.rng.choice(candidates or [0])
        self._last[(table, key)] = index
        return line_id(table, key, index), lines[index]
