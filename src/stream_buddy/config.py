"""設定ファイル (TOML) の読み込みと検証。

待ち受けアドレスは設定に含めない (SR-01)。`127.0.0.1` 固定はサーバー側のコードで行う。
"""

import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Annotated, Any, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)
from pydantic_core import ErrorDetails

Background = Literal["transparent", "chroma"]

# 指定値をエラーメッセージに含めない項目 (個人的な情報を含みうるため)
_HIDDEN_VALUE_LOCS = {("log", "output_dir"), ("lines", "file"), ("keywords", "model_dir")}
_MAX_SHOWN_VALUE_LEN = 40
# 廃止した項目と、代わりの案内
_REMOVED_KEYS = {
    ("log", "include_speech_text"): (
        "は廃止しました。話した文章はどこにも残らないため、代わりに include_keyword"
        "（キーワードで起きた死亡・クリアに、検知した言葉を添える）を使ってください"
    ),
}
# メモ帳などが先頭に付けることがある、UTF-8 の BOM
UTF8_BOM = b"\xef\xbb\xbf"


class ConfigError(Exception):
    """設定ファイルが読めない、または内容が正しくないときの例外。"""


def decode_utf8(data: bytes) -> str:
    """UTF-8 の文字列にする。先頭の BOM だけを取り除く (それ以外の位置の U+FEFF は残す)。"""
    return data.removeprefix(UTF8_BOM).decode("utf-8")


def _in_range[T: (int, float)](low: T, high: T) -> Callable[[T], T]:
    def check(value: T) -> T:
        if not low <= value <= high:
            raise ValueError(f"{low}〜{high} の範囲で指定してください")
        return value

    return check


def _check_keyword(value: str) -> str:
    if not 1 <= len(value) <= 20:
        raise ValueError("1〜20 文字で指定してください")
    return value


Keyword = Annotated[str, AfterValidator(_check_keyword)]
KeywordList = Annotated[tuple[Keyword, ...], Field(max_length=20, strict=False)]


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ServerConfig(_Section):
    port: Annotated[int, AfterValidator(_in_range(1024, 65535))] = 8765


class AudioConfig(_Section):
    device: str = ""
    speech_threshold_db: Annotated[float, AfterValidator(_in_range(-80.0, 0.0))] = -40.0


class SilenceConfig(_Section):
    seconds: Annotated[int, AfterValidator(_in_range(5, 600))] = 20


# ホットキーに使える修飾キー (正規の書き方の順) とキー (SR-05: これ以外は受け付けない)
HOTKEY_MODIFIERS = ("Ctrl", "Alt", "Shift")
HOTKEY_KEYS = tuple(f"F{n}" for n in range(1, 13))
_HOTKEY_FORMAT = "[Ctrl+][Alt+][Shift+]F1〜F12 の形で指定してください（例: F9、Ctrl+Shift+F9）"


@dataclass(frozen=True)
class HotkeySpec:
    """ホットキーの組み合わせ。modifiers は HOTKEY_MODIFIERS の順に並ぶ。"""

    modifiers: tuple[str, ...]
    key: str

    def __str__(self) -> str:
        return "+".join([*self.modifiers, self.key])


def parse_hotkey(text: str) -> HotkeySpec:
    """「Ctrl+Shift+F9」のような文字列を読む。修飾キーの順番と大文字・小文字は問わない。"""
    parts = [part.strip() for part in text.split("+")]
    *modifier_parts, key_part = parts
    by_lower = {name.lower(): name for name in HOTKEY_MODIFIERS}
    modifiers: set[str] = set()
    for part in modifier_parts:
        name = by_lower.get(part.lower())
        if name is None:
            raise ValueError(
                "修飾キーは Ctrl・Alt・Shift だけです（Win キーなどは使えません）。"
                + _HOTKEY_FORMAT
            )
        if name in modifiers:
            raise ValueError(f"同じ修飾キー（{name}）が重複しています。{_HOTKEY_FORMAT}")
        modifiers.add(name)
    key = key_part.upper()
    if key not in HOTKEY_KEYS:
        raise ValueError(f"キーは F1〜F12 のどれかにしてください。{_HOTKEY_FORMAT}")
    return HotkeySpec(tuple(m for m in HOTKEY_MODIFIERS if m in modifiers), key)


def _normalize_hotkey(value: str) -> str:
    # 書き方の揺れ (順番・大文字小文字) をなくし、正規の書き方で持つ
    return str(parse_hotkey(value))


Hotkey = Annotated[str, AfterValidator(_normalize_hotkey)]


class HotkeysConfig(_Section):
    death: Hotkey = "F9"
    clear: Hotkey = "F10"

    @model_validator(mode="after")
    def _keys_differ(self) -> Self:
        if self.death == self.clear:
            raise ValueError(f"death と clear に同じキーは指定できません（指定値: {self.death}）")
        return self


def _check_model_dir(value: str) -> str:
    # 空文字は既定の場所。指定するときは、どの OS で検証しても Windows の絶対パスとして判定する
    if value and not PureWindowsPath(value).is_absolute():
        raise ValueError("絶対パスで指定してください（空文字なら既定の場所）")
    return value


class KeywordsConfig(_Section):
    enabled: bool = True
    # 空文字なら <exe またはカレントフォルダ>/models/vosk-model-small-ja-0.22 (ADR 0003)
    model_dir: Annotated[str, AfterValidator(_check_model_dir)] = ""
    death: KeywordList = ("死んだ", "やられた")
    clear: KeywordList = ("クリア", "やったー")
    # おとりの言葉。似た音をキーワードに寄せないために文法に入れ、認識されたら検知なしにする
    decoys: KeywordList = ("やっぱり", "クリーム", "しんどい", "かったるい")

    @model_validator(mode="after")
    def _death_and_clear_differ(self) -> Self:
        both = sorted(set(self.death) & set(self.clear))
        if both:
            raise ValueError(f"death と clear に同じ言葉があります（{', '.join(both)}）")
        return self

    @model_validator(mode="after")
    def _keywords_and_decoys_differ(self) -> Self:
        both = sorted(set(self.death + self.clear) & set(self.decoys))
        if both:
            raise ValueError(
                f"キーワード（death・clear）とおとり（decoys）に同じ言葉があります"
                f"（{', '.join(both)}）"
            )
        return self


class DisplayConfig(_Section):
    background: Background = "transparent"


class LogConfig(_Section):
    enabled: bool = False
    output_dir: str = ""
    # true のとき、キーワードで起きた死亡・クリアに、検知した言葉 (設定に書いたキーワード) を添える
    include_keyword: bool = False

    @model_validator(mode="after")
    def _output_dir_required(self) -> Self:
        # 対象は Windows のみなので、どの OS で検証しても Windows のパスとして判定する
        if self.enabled and not PureWindowsPath(self.output_dir).is_absolute():
            raise ValueError("enabled = true のときは output_dir に絶対パスを指定してください")
        return self


def _check_lines_file(value: str) -> str:
    # 空文字は既定のセリフ集。指定するときは、どの OS で検証しても Windows の絶対パスとして判定する
    if value and not PureWindowsPath(value).is_absolute():
        raise ValueError("絶対パスで指定してください（空文字なら既定のセリフ集）")
    return value


class LinesConfig(_Section):
    file: Annotated[str, AfterValidator(_check_lines_file)] = ""


class Config(_Section):
    server: ServerConfig = ServerConfig()
    audio: AudioConfig = AudioConfig()
    silence: SilenceConfig = SilenceConfig()
    hotkeys: HotkeysConfig = HotkeysConfig()
    keywords: KeywordsConfig = KeywordsConfig()
    display: DisplayConfig = DisplayConfig()
    log: LogConfig = LogConfig()
    lines: LinesConfig = LinesConfig()


def load_config(path: Path | None) -> Config:
    """設定ファイルを読み込んで検証する。`None` やファイルがない場合は既定値を返す。"""
    if path is None or not path.exists():
        return Config()
    try:
        data = tomllib.loads(decode_utf8(path.read_bytes()))
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"設定ファイルが TOML として正しくありません: {e}") from None
    except UnicodeDecodeError:
        raise ConfigError("設定ファイルは UTF-8 で保存してください") from None
    except OSError as e:
        raise ConfigError(f"設定ファイルを読み込めません: {e.strerror}") from None
    try:
        return Config.model_validate(data)
    except ValidationError as e:
        messages = [_format_error(err) for err in e.errors()]
        raise ConfigError("設定ファイルに誤りがあります:\n" + "\n".join(messages)) from None


def _format_error(err: ErrorDetails) -> str:
    loc = err["loc"]
    where = _format_loc(loc)
    ctx: dict[str, Any] = err.get("ctx") or {}
    match err["type"]:
        case "extra_forbidden" if loc in _REMOVED_KEYS:
            return f"{where} {_REMOVED_KEYS[loc]}"
        case "extra_forbidden":
            return f"{where} は知らない項目です（書き間違いがないか確認してください）"
        case "value_error":
            reason = str(ctx.get("error", err["msg"]))
            # セクション全体の検証 (model_validator) の理由には指定値を含めてある
            if len(loc) <= 1:
                return f"{where} {reason}"
            return f"{where} は {reason}{_shown_value(loc, err['input'])}"
        case "literal_error":
            expected = str(ctx.get("expected", "")).replace(" or ", ", ")
            choices = f"{expected} のいずれか"
            return f"{where} は {choices}で指定してください{_shown_value(loc, err['input'])}"
        case "too_long":
            return (
                f"{where} は最大 {ctx.get('max_length')} 個までです"
                f"（指定数: {ctx.get('actual_length')}）"
            )
        case t if t.endswith("_type"):
            return f"{where} は {_type_name(t)}で指定してください{_shown_value(loc, err['input'])}"
        case _:
            return f"{where} の値が正しくありません（{err['msg']}）"


def _format_loc(loc: tuple[int | str, ...]) -> str:
    if not loc:
        return "設定全体"
    head = f"[{loc[0]}]"
    rest = [str(p) for p in loc[1:] if isinstance(p, str)]
    indexes = [p for p in loc[1:] if isinstance(p, int)]
    text = " ".join([head, *rest])
    if indexes:
        text += f" の {indexes[0] + 1} 番目"
    return text


def _type_name(error_type: str) -> str:
    names = {
        "int_type": "整数",
        "float_type": "数値",
        "string_type": '文字列（"..."）',
        "bool_type": "true または false ",
        "tuple_type": "配列（[...]）",
        "model_type": "セクション（[...]）",
    }
    return names.get(error_type, "正しい型")


def _shown_value(loc: tuple[int | str, ...], value: object) -> str:
    key = tuple(p for p in loc if isinstance(p, str))
    if key in _HIDDEN_VALUE_LOCS or not isinstance(value, int | float | str):
        return ""
    text = str(value)
    if len(text) > _MAX_SHOWN_VALUE_LEN:
        text = text[:_MAX_SHOWN_VALUE_LEN] + "…"
    return f"（指定値: {text}）"
