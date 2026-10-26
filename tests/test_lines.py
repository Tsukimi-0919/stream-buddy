import itertools
import json
import random
from pathlib import Path

import pytest

from stream_buddy.config import ConfigError
from stream_buddy.lines import (
    MAX_FILE_BYTES,
    SCHEMA,
    LineBook,
    LinePicker,
    LinesError,
    line_id,
    load_lines,
)
from stream_buddy.protocol import SayPayload


def rng(seed: int) -> random.Random:
    return random.Random(seed)  # noqa: S311  テストで結果を固定するための乱数 (暗号用途ではない)


ALL_LISTS = [(table, key) for table, keys in SCHEMA.items() for key in keys]


def toml_text(lists: dict[tuple[str, str], list[str]], extra: str = "") -> str:
    """(表, キー) ごとのリストから TOML を作る。文字列は JSON の書き方 (TOML と互換) で書く。"""
    tables: dict[str, list[str]] = {}
    for (table, key), lines in lists.items():
        items = ", ".join(json.dumps(line, ensure_ascii=False) for line in lines)
        tables.setdefault(table, []).append(f"{key} = [{items}]")
    body = "\n".join(f"[{t}]\n" + "\n".join(rows) for t, rows in tables.items())
    return body + "\n" + extra


def valid_lists(**override: list[str]) -> dict[tuple[str, str], list[str]]:
    """すべてのリストに 2 つずつセリフを入れたもの。override は "表__キー" で差し替える。"""
    lists = {k: [f"{k[0]}-{k[1]}-1", f"{k[0]}-{k[1]}-2"] for k in ALL_LISTS}
    for name, lines in override.items():
        table, key = name.split("__")
        lists[(table, key)] = lines
    return lists


def write(tmp_path: Path, text: str) -> str:
    path = tmp_path / "my-lines.toml"
    # 改行を変換せずに書く (サイズの上限を正確に試すため)
    path.write_bytes(text.encode("utf-8"))
    return str(path)


def load_error(tmp_path: Path, text: str) -> str:
    with pytest.raises(LinesError) as exc:
        load_lines(write(tmp_path, text))
    return str(exc.value)


# 既定のセリフ集


def test_default_lines_are_valid_and_complete() -> None:
    book = load_lines()
    assert set(book.lists) == set(ALL_LISTS)
    # silence の calm / normal / high、tension の high、event の death / clear
    assert len(ALL_LISTS) == 6
    for key in ALL_LISTS:
        assert book.get(*key)


def test_default_lines_are_valid_say_payloads() -> None:
    book = load_lines()
    for (table, key), lines in book.lists.items():
        for index, text in enumerate(lines):
            SayPayload(line_id=line_id(table, key, index), text=text)


def test_empty_file_setting_means_default() -> None:
    assert load_lines("") == load_lines()


def test_lines_error_is_a_config_error() -> None:
    # 起動時に設定のエラーと同じく扱える
    assert issubclass(LinesError, ConfigError)


# 自分のセリフ集


def test_custom_file_is_loaded(tmp_path: Path) -> None:
    book = load_lines(write(tmp_path, toml_text(valid_lists(event__death=["やられた〜"]))))
    assert book.get("event", "death") == ("やられた〜",)


@pytest.mark.parametrize("file", ["lines.toml", "data\\lines.toml", "C:lines.toml", "\\lines.toml"])
def test_relative_path_is_error(file: str) -> None:
    with pytest.raises(LinesError, match="絶対パス"):
        load_lines(file)


def test_missing_file_is_error_not_default(tmp_path: Path) -> None:
    with pytest.raises(LinesError, match="読み込めません"):
        load_lines(str(tmp_path / "nothing.toml"))


def test_broken_toml_is_error(tmp_path: Path) -> None:
    assert "TOML として正しくありません" in load_error(tmp_path, "[event\ndeath = []\n")


def test_not_utf8_is_error(tmp_path: Path) -> None:
    path = tmp_path / "lines.toml"
    path.write_bytes(toml_text(valid_lists(event__death=["死んだ"])).encode("cp932"))
    with pytest.raises(LinesError, match="UTF-8"):
        load_lines(str(path))


def test_file_up_to_64kb_is_ok(tmp_path: Path) -> None:
    text = toml_text(valid_lists())
    padding = MAX_FILE_BYTES - len(text.encode("utf-8")) - 2
    load_lines(write(tmp_path, text + "#" + "x" * padding + "\n"))


def test_file_over_64kb_is_error(tmp_path: Path) -> None:
    text = toml_text(valid_lists())
    padding = MAX_FILE_BYTES - len(text.encode("utf-8")) - 1
    assert "大きすぎます" in load_error(tmp_path, text + "#" + "x" * padding + "\n")


# 検証


def test_unknown_table(tmp_path: Path) -> None:
    message = load_error(tmp_path, toml_text(valid_lists(), extra='[greeting]\nhello = ["やあ"]\n'))
    assert "[greeting] は知らない表です" in message


def test_unknown_key(tmp_path: Path) -> None:
    lists = valid_lists()
    lists[("event", "win")] = ["勝ち"]
    assert "[event] win は知らない項目です" in load_error(tmp_path, toml_text(lists))


def test_missing_list(tmp_path: Path) -> None:
    lists = valid_lists()
    del lists[("silence", "normal")]
    assert "[silence] normal がありません" in load_error(tmp_path, toml_text(lists))


def test_missing_table(tmp_path: Path) -> None:
    lists = {k: v for k, v in valid_lists().items() if k[0] != "tension"}
    assert "[tension] がありません" in load_error(tmp_path, toml_text(lists))


def test_not_a_list(tmp_path: Path) -> None:
    text = toml_text(valid_lists()).replace(
        'high = ["tension-high-1", "tension-high-2"]', 'high = "a"'
    )
    assert "[tension] high は配列" in load_error(tmp_path, text)


def test_empty_list(tmp_path: Path) -> None:
    message = load_error(tmp_path, toml_text(valid_lists(event__clear=[])))
    assert "[event] clear のセリフが 0 個です（1〜30 個にしてください）" in message


def test_30_lines_ok_31_lines_error(tmp_path: Path) -> None:
    load_lines(write(tmp_path, toml_text(valid_lists(event__clear=[f"{i}" for i in range(30)]))))
    lines = [f"{i}" for i in range(31)]
    message = load_error(tmp_path, toml_text(valid_lists(event__clear=lines)))
    assert "[event] clear のセリフが 31 個です（1〜30 個にしてください）" in message


def test_80_chars_ok_81_chars_error(tmp_path: Path) -> None:
    # len() で数える。全角も 1 文字
    load_lines(write(tmp_path, toml_text(valid_lists(event__death=["あ" * 80]))))
    lines = ["ok", "ok", "あ" * 81]
    message = load_error(tmp_path, toml_text(valid_lists(event__death=lines)))
    assert "[event] death の 3 番目が 81 文字です（上限 80 文字）" in message


@pytest.mark.parametrize("line", ["", " ", "　 　"])
def test_blank_line_is_error(tmp_path: Path, line: str) -> None:
    message = load_error(tmp_path, toml_text(valid_lists(silence__calm=[line])))
    assert "[silence] calm の 1 番目が空です" in message


@pytest.mark.parametrize(
    ("line", "reason"),
    [
        ("ボク\nメンダコ", "改行"),
        ("ボク\r\nメンダコ", "改行"),
        ("ボク\u2028メンダコ", "改行"),
        ("ボク\tメンダコ", "タブ"),
        ("ボク\u0007メンダコ", "制御文字（U+0007）"),
        ("ボク​メンダコ", "制御文字（U+200B）"),
        ("ボク‮メンダコ", "制御文字（U+202E）"),
    ],
)
def test_control_characters_are_error(tmp_path: Path, line: str, reason: str) -> None:
    message = load_error(tmp_path, toml_text(valid_lists(tension__high=["ok", line])))
    assert f"[tension] high の 2 番目に{reason}が含まれています" in message


def test_non_string_is_error(tmp_path: Path) -> None:
    text = toml_text(valid_lists()).replace('"event-death-1"', "42")
    assert "[event] death の 1 番目が文字列ではありません" in load_error(tmp_path, text)


@pytest.mark.parametrize(
    "line",
    [
        "やったー🔥",
        "GG🎉",
        "家族👨‍👩‍👧",  # ゼロ幅接合子
        "好き❤️",  # 異体字セレクタ
        "ボク　メンダコ",  # 全角の空白
    ],
)
def test_emoji_is_ok(tmp_path: Path, line: str) -> None:
    book = load_lines(write(tmp_path, toml_text(valid_lists(event__clear=[line]))))
    assert book.get("event", "clear") == (line,)


def test_all_errors_are_reported_together(tmp_path: Path) -> None:
    lists = valid_lists(event__death=["あ" * 81], silence__high=[])
    message = load_error(tmp_path, toml_text(lists))
    assert "[event] death の 1 番目" in message
    assert "[silence] high のセリフが 0 個" in message


def test_error_message_does_not_contain_line_or_path(tmp_path: Path) -> None:
    secret = "ひみつのセリフ" * 12
    path = write(tmp_path, toml_text(valid_lists(event__death=[secret])))
    with pytest.raises(LinesError) as exc:
        load_lines(path)
    assert secret not in str(exc.value)
    assert "ひみつ" not in str(exc.value)
    assert str(tmp_path) not in str(exc.value)
    with pytest.raises(LinesError) as exc:
        load_lines(str(tmp_path / "private-folder" / "nothing.toml"))
    assert "private-folder" not in str(exc.value)


# 選び方


def book_of(**lists: list[str]) -> LineBook:
    return LineBook({k: tuple(v) for k, v in valid_lists(**lists).items()})


def test_pick_returns_line_id_and_text() -> None:
    picker = LinePicker(book_of(event__death=["ちーん"]))
    assert picker.pick("death", "calm") == ("event.death.1", "ちーん")


@pytest.mark.parametrize("seed", range(20))
def test_pick_never_repeats_the_previous_line(seed: int) -> None:
    picker = LinePicker(book_of(event__clear=["a", "b", "c"]), rng(seed))
    picked = [picker.pick("clear", "normal")[0] for _ in range(200)]
    assert all(a != b for a, b in itertools.pairwise(picked))
    # 偏りなく、どれも選ばれる
    assert set(picked) == {"event.clear.1", "event.clear.2", "event.clear.3"}


def test_pick_with_one_candidate_repeats() -> None:
    picker = LinePicker(book_of(tension__high=["キタ"]), rng(0))
    assert [picker.pick("high", "high") for _ in range(3)] == [("tension.high.1", "キタ")] * 3


def test_previous_line_is_remembered_per_list() -> None:
    picker = LinePicker(book_of(silence__calm=["a", "b"], silence__high=["x", "y"]))
    for _ in range(50):
        first = picker.pick("silence", "calm")
        picker.pick("silence", "high")  # 別のリストを挟んでも
        assert picker.pick("silence", "calm") != first


@pytest.mark.parametrize("tension", ["calm", "normal", "high"])
def test_silence_uses_list_for_tension(tension: str) -> None:
    picker = LinePicker(book_of())
    for _ in range(5):
        lid, text = picker.pick("silence", tension)  # type: ignore[arg-type]
        assert lid.startswith(f"silence.{tension}.")
        assert text.startswith(f"silence-{tension}-")


def test_situations_map_to_lists() -> None:
    picker = LinePicker(book_of())
    assert picker.pick("high", "calm")[0].startswith("tension.high.")
    assert picker.pick("death", "high")[0].startswith("event.death.")
    assert picker.pick("clear", "high")[0].startswith("event.clear.")


def test_fixed_seed_gives_fixed_result() -> None:
    book = load_lines()

    def run(seed: int) -> list[tuple[str, str]]:
        picker = LinePicker(book, rng(seed))
        return [picker.pick("silence", "normal") for _ in range(10)]

    assert run(42) == run(42)
    assert run(1) != run(2)
