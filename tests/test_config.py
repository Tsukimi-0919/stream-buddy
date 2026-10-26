from pathlib import Path

import pytest
from pydantic import ValidationError

from stream_buddy.config import UTF8_BOM, Config, ConfigError, load_config

EXAMPLE = Path(__file__).parent.parent / "config.example.toml"


def write_config(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(text, encoding="utf-8")
    return path


def load_error(tmp_path: Path, text: str) -> str:
    with pytest.raises(ConfigError) as exc:
        load_config(write_config(tmp_path, text))
    return str(exc.value)


def test_none_returns_defaults() -> None:
    assert load_config(None) == Config()


def test_missing_file_returns_defaults(tmp_path: Path) -> None:
    assert load_config(tmp_path / "nothing.toml") == Config()


def test_defaults() -> None:
    config = Config()
    assert config.server.port == 8765
    assert config.audio.device == ""
    assert config.audio.speech_threshold_db == -40.0
    assert config.silence.seconds == 20
    assert config.hotkeys.death == "F9"
    assert config.hotkeys.clear == "F10"
    assert config.keywords.enabled is True
    assert config.keywords.model_dir == ""
    assert config.keywords.death == ("死んだ", "やられた")
    assert config.keywords.clear == ("クリア", "やったー")
    assert config.keywords.decoys == ("やっぱり", "クリーム", "しんどい", "かったるい")
    assert config.display.background == "transparent"
    assert config.log.enabled is False
    assert config.log.output_dir == ""
    assert config.log.include_speech_text is False
    assert config.lines.file == ""


def test_example_file_matches_defaults() -> None:
    assert load_config(EXAMPLE) == Config()


def test_partial_file_fills_defaults(tmp_path: Path) -> None:
    config = load_config(write_config(tmp_path, "[server]\nport = 9000\n"))
    assert config.server.port == 9000
    assert config.silence.seconds == 20


def test_valid_values(tmp_path: Path) -> None:
    text = """
[audio]
speech_threshold_db = -30
[hotkeys]
death = "F1"
clear = "F12"
[keywords]
death = ["負けた"]
[display]
background = "chroma"
[log]
enabled = true
output_dir = 'C:\\stream-logs'
"""
    config = load_config(write_config(tmp_path, text))
    assert config.audio.speech_threshold_db == -30.0
    assert config.hotkeys.death == "F1"
    assert config.keywords.death == ("負けた",)
    assert config.display.background == "chroma"
    assert config.log.output_dir == "C:\\stream-logs"


@pytest.mark.parametrize("port", [80, 1023, 65536])
def test_port_out_of_range(tmp_path: Path, port: int) -> None:
    message = load_error(tmp_path, f"[server]\nport = {port}\n")
    assert f"[server] port は 1024〜65535 の範囲で指定してください（指定値: {port}）" in message


def test_port_wrong_type(tmp_path: Path) -> None:
    message = load_error(tmp_path, '[server]\nport = "8765"\n')
    assert "[server] port は 整数で指定してください" in message


def test_host_is_not_configurable(tmp_path: Path) -> None:
    message = load_error(tmp_path, '[server]\nhost = "0.0.0.0"\n')
    assert "[server] host は知らない項目です" in message


def test_unknown_key(tmp_path: Path) -> None:
    message = load_error(tmp_path, "[silence]\nsecond = 20\n")
    assert "[silence] second は知らない項目です" in message


def test_unknown_section(tmp_path: Path) -> None:
    message = load_error(tmp_path, "[sound]\nvolume = 1\n")
    assert "[sound] は知らない項目です" in message


@pytest.mark.parametrize(
    ("section", "text"), [("audio", "speech_threshold_db = 1.0"), ("silence", "seconds = 4")]
)
def test_other_ranges(tmp_path: Path, section: str, text: str) -> None:
    message = load_error(tmp_path, f"[{section}]\n{text}\n")
    assert f"[{section}]" in message
    assert "の範囲で指定してください" in message


@pytest.mark.parametrize("key", ["F13", "F0", "A", "Ctrl+F9", "f9"])
def test_invalid_hotkey(tmp_path: Path, key: str) -> None:
    message = load_error(tmp_path, f'[hotkeys]\ndeath = "{key}"\n')
    assert "[hotkeys] death は" in message
    assert f"（指定値: {key}）" in message


def test_same_hotkeys(tmp_path: Path) -> None:
    message = load_error(tmp_path, '[hotkeys]\ndeath = "F5"\nclear = "F5"\n')
    assert "[hotkeys] death と clear に同じキーは指定できません（指定値: F5）" in message


def test_keyword_too_long(tmp_path: Path) -> None:
    message = load_error(tmp_path, f'[keywords]\ndeath = ["死んだ", "{"あ" * 21}"]\n')
    assert "[keywords] death の 2 番目 は 1〜20 文字で指定してください" in message


def test_keyword_empty(tmp_path: Path) -> None:
    message = load_error(tmp_path, '[keywords]\nclear = [""]\n')
    assert "[keywords] clear の 1 番目 は 1〜20 文字で指定してください" in message


def test_too_many_keywords(tmp_path: Path) -> None:
    words = ", ".join(f'"w{i}"' for i in range(21))
    message = load_error(tmp_path, f"[keywords]\ndeath = [{words}]\n")
    assert "[keywords] death は最大 20 個までです（指定数: 21）" in message


def test_invalid_background(tmp_path: Path) -> None:
    message = load_error(tmp_path, '[display]\nbackground = "green"\n')
    assert "[display] background は 'transparent', 'chroma' のいずれかで" in message


@pytest.mark.parametrize("output_dir", ["", "logs", "logs\\stream", "C:logs", "\\logs"])
def test_log_enabled_requires_absolute_output_dir(tmp_path: Path, output_dir: str) -> None:
    text = f"[log]\nenabled = true\noutput_dir = '{output_dir}'\n"
    message = load_error(tmp_path, text)
    assert "[log] enabled = true のときは output_dir に絶対パスを指定してください" in message


def test_log_disabled_allows_empty_output_dir(tmp_path: Path) -> None:
    config = load_config(write_config(tmp_path, "[log]\nenabled = false\n"))
    assert config.log.output_dir == ""


def test_lines_file_absolute_path(tmp_path: Path) -> None:
    config = load_config(write_config(tmp_path, "[lines]\nfile = 'C:\\stream\\my-lines.toml'\n"))
    assert config.lines.file == "C:\\stream\\my-lines.toml"


@pytest.mark.parametrize("file", ["lines.toml", "data\\lines.toml", "C:lines.toml", "\\lines.toml"])
def test_lines_file_relative_path_is_error(tmp_path: Path, file: str) -> None:
    message = load_error(tmp_path, f"[lines]\nfile = '{file}'\n")
    assert "[lines] file は 絶対パスで指定してください" in message
    # パスには個人のフォルダ名が入りうるので、指定値は出さない
    assert "指定値" not in message


def test_lines_unknown_key(tmp_path: Path) -> None:
    assert "[lines] path は知らない項目です" in load_error(tmp_path, "[lines]\npath = ''\n")


def test_broken_toml(tmp_path: Path) -> None:
    message = load_error(tmp_path, "[server\nport = 8765\n")
    assert "TOML として正しくありません" in message


def test_not_utf8(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_bytes('[audio]\ndevice = "マイク"\n'.encode("cp932"))
    with pytest.raises(ConfigError):
        load_config(path)


def test_utf8_with_bom(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_bytes(UTF8_BOM + '[audio]\ndevice = "マイク"\n'.encode())
    assert load_config(path).audio.device == "マイク"
    path.write_bytes(UTF8_BOM + EXAMPLE.read_bytes())
    assert load_config(path) == Config()


def test_bom_is_removed_only_at_the_start(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    # 文字列の中の U+FEFF は取り除かずに残す
    path.write_bytes(UTF8_BOM + '[audio]\ndevice = "\ufeffマイク"\n'.encode())
    assert load_config(path).audio.device == "\ufeffマイク"
    # 2 つ目の BOM は TOML の一部として扱われ、エラーになる
    path.write_bytes(UTF8_BOM * 2 + b"[server]\nport = 8765\n")
    with pytest.raises(ConfigError, match="TOML として正しくありません"):
        load_config(path)


def test_error_message_does_not_contain_path_or_content(tmp_path: Path) -> None:
    private_dir = "my-private-folder"
    text = f"[log]\nenabled = true\noutput_dir = '{private_dir}'\n[server]\nport = 1\n"
    message = load_error(tmp_path, text)
    assert private_dir not in message
    assert str(tmp_path) not in message


def test_config_is_frozen() -> None:
    config = load_config(EXAMPLE)
    with pytest.raises(ValidationError):
        config.server.port = 9000  # type: ignore[misc]
    with pytest.raises(ValidationError):
        config.server = config.server  # type: ignore[misc]
    with pytest.raises(AttributeError):
        config.keywords.death.append("x")  # type: ignore[attr-defined]
