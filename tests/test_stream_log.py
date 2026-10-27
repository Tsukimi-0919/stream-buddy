"""配信ログのテスト。時計は偽物に差し替え、ファイルは一時フォルダに書く。"""

import asyncio
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from stream_buddy import app, demo, server, stream_log
from stream_buddy.__main__ import main
from stream_buddy.config import Config, ConfigError, LogConfig, SilenceConfig, load_config
from stream_buddy.lines import load_lines
from stream_buddy.protocol import ServerMessage
from stream_buddy.state import events as ev
from stream_buddy.stream_log import StreamLog, StreamLogError, file_names, open_stream_log

START = datetime(2026, 10, 27, 20, 0, 12)  # ログはローカル時刻で書く
FIRST_NAME = "stream-buddy-2026-10-27-200012.md"
TICK = 100


class FakeClock:
    """壁時計と monotonic をいっしょに進める。wall_offset で壁時計だけをずらせる。"""

    def __init__(self) -> None:
        self.elapsed = 0.0
        self.wall_offset = timedelta()

    def now(self) -> datetime:
        return START + timedelta(seconds=self.elapsed) + self.wall_offset

    def monotonic(self) -> float:
        return 1_000.0 + self.elapsed

    def advance(self, seconds: float) -> None:
        self.elapsed += seconds


def log_config(folder: Path, *, include_keyword: bool = False) -> LogConfig:
    return LogConfig(enabled=True, output_dir=str(folder), include_keyword=include_keyword)


def open_log(folder: Path, clock: FakeClock, *, include_keyword: bool = False) -> StreamLog:
    log = open_stream_log(
        log_config(folder, include_keyword=include_keyword),
        now=clock.now,
        monotonic=clock.monotonic,
    )
    assert log is not None
    return log


def only_file(folder: Path) -> Path:
    files = list(folder.iterdir())
    assert len(files) == 1
    return files[0]


def read(path: Path) -> str:
    data = path.read_bytes()
    assert not data.startswith(b"\xef\xbb\xbf")  # BOM なし
    assert b"\r" not in data  # 改行は LF
    return data.decode("utf-8")


def rows(text: str) -> list[list[str]]:
    """表の行 (見出しと区切りを除く)。"""
    lines = [line for line in text.splitlines() if line.startswith("| ")]
    return [[cell.strip() for cell in line.strip("|").split("|")] for line in lines[2:]]


# 有効・無効


def test_disabled_creates_no_file(tmp_path: Path) -> None:
    assert open_stream_log(LogConfig(), now=FakeClock().now) is None
    disabled = LogConfig(enabled=False, output_dir=str(tmp_path))
    assert open_stream_log(disabled) is None
    assert list(tmp_path.iterdir()) == []


# 起動時の確認


def test_missing_output_dir_is_error_and_not_created(tmp_path: Path) -> None:
    missing = tmp_path / "logs"
    with pytest.raises(StreamLogError, match="フォルダがありません"):
        open_stream_log(log_config(missing), now=FakeClock().now)
    assert not missing.exists()  # フォルダは作らない


def test_output_dir_that_is_a_file_is_error(tmp_path: Path) -> None:
    file = tmp_path / "logs"
    file.write_text("ファイル", encoding="utf-8")
    with pytest.raises(StreamLogError, match="フォルダを指定してください"):
        open_stream_log(log_config(file), now=FakeClock().now)
    assert file.read_text(encoding="utf-8") == "ファイル"


def test_unwritable_output_dir_is_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def deny(*_: object, **__: object) -> None:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(Path, "open", deny)
    with pytest.raises(StreamLogError, match="書き込めません"):
        open_stream_log(log_config(tmp_path), now=FakeClock().now)


def test_errors_do_not_show_the_path(tmp_path: Path) -> None:
    folder = tmp_path / "秘密のフォルダ"
    with pytest.raises(StreamLogError) as e:
        open_stream_log(log_config(folder), now=FakeClock().now)
    assert "秘密のフォルダ" not in str(e.value)
    assert str(tmp_path) not in str(e.value)


def test_stream_log_error_stops_startup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []
    monkeypatch.setattr(server, "serve", lambda *a, **kw: calls.append(kw))
    monkeypatch.chdir(tmp_path)
    config = tmp_path / "config.toml"
    missing = str(tmp_path / "logs").replace("\\", "\\\\")
    config.write_text(f'[log]\nenabled = true\noutput_dir = "{missing}"\n', encoding="utf-8")
    assert main(["--config", str(config), "--demo"]) == 2
    assert calls == []  # サーバーを始めない
    assert not (tmp_path / "logs").exists()


# ファイル名と書き込み先


def test_file_name_comes_from_start_time(tmp_path: Path) -> None:
    open_log(tmp_path, FakeClock()).close()
    assert only_file(tmp_path).name == FIRST_NAME
    assert file_names(START)[:3] == [
        FIRST_NAME,
        "stream-buddy-2026-10-27-200012-2.md",
        "stream-buddy-2026-10-27-200012-3.md",
    ]
    assert len(file_names(START)) == stream_log.MAX_ATTEMPTS


def test_existing_file_is_not_overwritten(tmp_path: Path) -> None:
    (tmp_path / FIRST_NAME).write_text("前の配信", encoding="utf-8")
    open_log(tmp_path, FakeClock()).close()
    open_log(tmp_path, FakeClock()).close()
    assert (tmp_path / FIRST_NAME).read_text(encoding="utf-8") == "前の配信"
    assert {p.name for p in tmp_path.iterdir()} == {
        FIRST_NAME,
        "stream-buddy-2026-10-27-200012-2.md",
        "stream-buddy-2026-10-27-200012-3.md",
    }


def test_error_after_max_attempts(tmp_path: Path) -> None:
    for name in file_names(START):
        (tmp_path / name).write_text("前の配信", encoding="utf-8")
    with pytest.raises(StreamLogError, match="10 回"):
        open_log(tmp_path, FakeClock())
    assert all(p.read_text(encoding="utf-8") == "前の配信" for p in tmp_path.iterdir())


def test_file_is_directly_under_output_dir(tmp_path: Path) -> None:
    # 「..」を含む書き方でも、正規化した output_dir の直下に作る
    folder = tmp_path / "vault" / "logs"
    folder.mkdir(parents=True)
    roundabout = tmp_path / "vault" / "other" / ".." / "logs"
    open_log(roundabout, FakeClock()).close()
    created = only_file(folder)
    assert created.resolve().parent == folder.resolve()
    assert not (tmp_path / "vault" / "other").exists()


# 書く内容


def test_content_has_front_matter_table_rows_and_summary(tmp_path: Path) -> None:
    clock = FakeClock()
    log = open_log(tmp_path, clock)
    clock.advance(12 * 60 + 34)
    log.peak()
    clock.advance(2 * 60 + 28)
    log.effect("clear")
    clock.advance(16 * 60 + 38)
    log.effect("death", "死んだ")  # include_keyword = false なので添えない
    clock.advance(30 * 60 + 35)
    log.close()
    assert read(only_file(tmp_path)) == (
        "---\n"
        "date: 2026-10-27\n"
        'start: "20:00:12"\n'
        "tags: [stream-buddy]\n"
        "---\n"
        "# 配信ログ 2026-10-27 20:00\n"
        "\n"
        "| 経過 | 時刻 | できごと |\n"
        "| --- | --- | --- |\n"
        "| 00:12:34 | 20:12:46 | テンション High |\n"
        "| 00:15:02 | 20:15:14 | クリア |\n"
        "| 00:31:40 | 20:31:52 | 死亡 |\n"
        "\n"
        "## まとめ\n"
        "\n"
        "- 配信時間：1:02:15\n"
        "- テンション High：1 回\n"
        "- 死亡：1 回\n"
        "- クリア：1 回\n"
    )


def test_elapsed_uses_monotonic_and_time_uses_wall_clock(tmp_path: Path) -> None:
    clock = FakeClock()
    log = open_log(tmp_path, clock)
    clock.advance(65)
    clock.wall_offset = timedelta(hours=-1)  # 途中で PC の時計が 1 時間戻った
    log.peak()
    log.close()
    assert rows(read(only_file(tmp_path))) == [["00:01:05", "19:01:17", "テンション High"]]


def test_elapsed_and_duration_formats(tmp_path: Path) -> None:
    clock = FakeClock()
    log = open_log(tmp_path, clock)
    clock.advance(10 * 3600 + 5)
    log.effect("death")
    log.close()
    text = read(only_file(tmp_path))
    assert rows(text)[0][0] == "10:00:05"
    assert "- 配信時間：10:00:05\n" in text
    for row in rows(text):
        assert re.fullmatch(r"\d{2,}:\d{2}:\d{2}", row[0])
        assert re.fullmatch(r"\d{2}:\d{2}:\d{2}", row[1])


def test_summary_counts(tmp_path: Path) -> None:
    clock = FakeClock()
    log = open_log(tmp_path, clock)
    for _ in range(3):
        log.peak()
    for _ in range(5):
        log.effect("death")
    for _ in range(2):
        log.effect("clear")
    clock.advance(59)
    log.close()
    text = read(only_file(tmp_path))
    assert text.endswith(
        "## まとめ\n\n- 配信時間：0:00:59\n- テンション High：3 回\n- 死亡：5 回\n- クリア：2 回\n"
    )
    assert len(rows(text)) == 10


def test_close_twice_writes_summary_once(tmp_path: Path) -> None:
    log = open_log(tmp_path, FakeClock())
    log.close()
    log.close()
    log.peak()  # 閉じたあとは書かない
    text = read(only_file(tmp_path))
    assert text.count("## まとめ") == 1
    assert rows(text) == []


# include_keyword


def test_include_keyword_false_does_not_add_word(tmp_path: Path) -> None:
    log = open_log(tmp_path, FakeClock(), include_keyword=False)
    log.effect("death", "死んだ")
    log.effect("clear", "やったー")
    log.close()
    text = read(only_file(tmp_path))
    assert [row[2] for row in rows(text)] == ["死亡", "クリア"]
    assert "死んだ" not in text
    assert "やったー" not in text


def test_include_keyword_true_adds_word_only_for_keyword(tmp_path: Path) -> None:
    log = open_log(tmp_path, FakeClock(), include_keyword=True)
    log.effect("death", "死んだ")  # キーワード
    log.effect("clear")  # ホットキー
    log.effect("clear", "やったー")
    log.close()
    assert [row[2] for row in rows(read(only_file(tmp_path)))] == [
        "死亡（死んだ）",
        "クリア",
        "クリア（やったー）",
    ]


def test_table_cells_drop_pipes_and_newlines(tmp_path: Path) -> None:
    log = open_log(tmp_path, FakeClock(), include_keyword=True)
    log.effect("death", "死|ん\nだ\r")
    log.close()
    text = read(only_file(tmp_path))
    assert rows(text) == [["00:00:00", "20:00:12", "死亡（死んだ）"]]


# その場で書き足す・途中で落ちたとき


def test_each_event_is_written_before_close(tmp_path: Path) -> None:
    clock = FakeClock()
    log = open_log(tmp_path, clock)
    path = only_file(tmp_path)
    assert "| 経過 | 時刻 | できごと |" in read(path)  # 開いた時点で見出しがある
    log.peak()
    assert [row[2] for row in rows(read(path))] == ["テンション High"]
    clock.advance(1)
    log.effect("death")
    assert [row[2] for row in rows(read(path))] == ["テンション High", "死亡"]
    assert "## まとめ" not in read(path)
    log.close()


def test_rows_remain_when_summary_cannot_be_written(tmp_path: Path) -> None:
    log = open_log(tmp_path, FakeClock())
    log.peak()
    log.effect("clear")
    file: Any = log._file

    def broken(_: str) -> int:
        raise OSError(28, "No space left on device")

    file.write = broken
    log.close()  # まとめは書けないが、例外で止まらず閉じる
    assert file.closed
    text = read(only_file(tmp_path))
    assert [row[2] for row in rows(text)] == ["テンション High", "クリア"]
    assert "## まとめ" not in text


# Engine とつないだとき


class LoggedSim:
    """差し替えた時計で Engine を動かし、配信ログに書く。"""

    def __init__(self, folder: Path, *, include_keyword: bool = False) -> None:
        self.now = 0
        self.clock = FakeClock()
        self.log = open_log(folder, self.clock, include_keyword=include_keyword)
        self.engine = app.Engine(
            Config(silence=SilenceConfig(seconds=20)),
            load_lines(),
            clock=lambda: self.now,
            log=self.log,
        )
        self.sent: list[ServerMessage] = []

    async def _broadcast(self, message: ServerMessage) -> None:
        self.sent.append(message)

    def at(self, when: int, *items: app.QueueItem) -> None:
        asyncio.run(self._run(when, items))

    async def _run(self, when: int, items: tuple[app.QueueItem, ...]) -> None:
        while self.now + TICK <= when:
            self.now += TICK
            self.clock.advance(TICK / 1000)
            await self.engine.handle(ev.Tick(), self._broadcast)
        self.clock.advance((when - self.now) / 1000)
        self.now = when
        for item in items:
            await self.engine.handle(item, self._broadcast)


def heard(kind: ev.EventKind, word: str) -> app.HeardKeyword:
    return app.HeardKeyword(ev.Keyword(kind), word)


def test_engine_writes_peak_and_effects(tmp_path: Path) -> None:
    sim = LoggedSim(tmp_path, include_keyword=True)
    sim.at(0, ev.SpeechStarted())
    sim.at(30_000, ev.SpeechEnded())  # 21 秒で High
    sim.at(31_000, heard("death", "死んだ"))
    sim.at(40_000, ev.Hotkey("clear"))
    sim.log.close()
    assert rows(read(only_file(tmp_path))) == [
        ["00:00:21", "20:00:33", "テンション High"],
        ["00:00:31", "20:00:43", "死亡（死んだ）"],
        ["00:00:40", "20:00:52", "クリア"],  # ホットキーには言葉を添えない
    ]
    # ページへの送信は今までどおり
    assert [m.payload.model_dump() for m in sim.sent if m.type == "effect"] == [
        {"kind": "death"},
        {"kind": "clear"},
    ]


def test_ignored_keyword_does_not_lend_word_to_later_effect(tmp_path: Path) -> None:
    sim = LoggedSim(tmp_path, include_keyword=True)
    sim.at(1_000, heard("death", "死んだ"))
    sim.at(2_000, heard("death", "やられた"))  # 演出中なので無視 (Effect は出ない)
    sim.at(10_000, ev.Hotkey("death"))
    sim.log.close()
    assert [row[2] for row in rows(read(only_file(tmp_path)))] == ["死亡（死んだ）", "死亡"]


def test_log_has_no_token_path_or_lines(tmp_path: Path) -> None:
    sim = LoggedSim(tmp_path, include_keyword=True)
    for at, event in demo.demo_script(20):
        sim.at(at, event)
    sim.at(demo.cycle_ms(20))
    sim.log.close()
    text = read(only_file(tmp_path))
    assert {row[2] for row in rows(text)} == {"テンション High", "死亡", "クリア"}
    # セリフは送られているが、ログには入らない
    said = [m.payload.model_dump()["text"] for m in sim.sent if m.type == "say"]
    assert said
    for line in [text for texts in load_lines().lists.values() for text in texts]:
        assert line not in text
    assert str(tmp_path) not in text
    assert "\\" not in text
    assert "token" not in text


def test_main_demo_writes_log_and_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def broadcast(_message: ServerMessage) -> None:
        pass

    def serve_briefly(_config: Config, _token: str, *, running: Any, **_: Any) -> None:
        async def run() -> None:
            async with running(broadcast):
                await asyncio.sleep(0.3)

        asyncio.run(run())

    monkeypatch.setattr(server, "serve", serve_briefly)
    monkeypatch.chdir(tmp_path)
    folder = tmp_path / "logs"
    folder.mkdir()
    config = tmp_path / "config.toml"
    escaped = str(folder).replace("\\", "\\\\")
    config.write_text(f'[log]\nenabled = true\noutput_dir = "{escaped}"\n', encoding="utf-8")
    assert main(["--config", str(config), "--demo"]) == 0
    text = read(only_file(folder))
    assert text.startswith("---\ndate: ")
    assert "## まとめ" in text
    token = capsys.readouterr().out.split("/overlay?token=")[1].split()[0]
    assert token not in text


@pytest.mark.parametrize("error", [RuntimeError("サーバーが起動できない"), KeyboardInterrupt()])
def test_main_writes_summary_when_server_stops_with_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: BaseException
) -> None:
    def fail(*_: object, **__: object) -> None:
        raise error

    monkeypatch.setattr(server, "serve", fail)
    monkeypatch.chdir(tmp_path)
    folder = tmp_path / "logs"
    folder.mkdir()
    config = tmp_path / "config.toml"
    escaped = str(folder).replace("\\", "\\\\")
    config.write_text(f'[log]\nenabled = true\noutput_dir = "{escaped}"\n', encoding="utf-8")
    with pytest.raises(type(error)):
        main(["--config", str(config), "--demo"])
    assert read(only_file(folder)).endswith("- クリア：0 回\n")


# 起動をやめたとき (abandon)


def write_log_config(tmp_path: Path, folder: Path, extra: str = "") -> Path:
    config = tmp_path / "config.toml"
    escaped = str(folder).replace("\\", "\\\\")
    config.write_text(f'{extra}[log]\nenabled = true\noutput_dir = "{escaped}"\n', encoding="utf-8")
    return config


def test_main_startup_failure_leaves_no_new_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    calls: list[object] = []
    monkeypatch.setattr(server, "serve", lambda *a, **kw: calls.append(kw))
    monkeypatch.chdir(tmp_path)
    folder = tmp_path / "logs"
    folder.mkdir()
    previous = folder / "stream-buddy-2026-10-26-210000.md"
    previous.write_text("前回の配信", encoding="utf-8")
    other = folder / "メモ.md"
    other.write_text("ほかのメモ", encoding="utf-8")
    # マイクが見つからないので、ログのファイルを作ったあとで起動をやめる
    config = write_log_config(tmp_path, folder, '[audio]\ndevice = "Blue Yeti"\n\n')
    assert main(["--config", str(config)]) == 2
    assert calls == []
    # 作ったファイルだけが消え、前回のログやほかのファイルは残る
    assert {p.name for p in folder.iterdir()} == {previous.name, other.name}
    assert previous.read_text(encoding="utf-8") == "前回の配信"
    assert other.read_text(encoding="utf-8") == "ほかのメモ"
    assert "配信ログ" not in caplog.text  # 消せたので警告は出ない


def test_abandon_removes_only_own_file_when_no_events(tmp_path: Path) -> None:
    (tmp_path / FIRST_NAME).write_text("前回の配信", encoding="utf-8")
    log = open_log(tmp_path, FakeClock())  # 同じ名前があるので -2 を作る
    assert (tmp_path / "stream-buddy-2026-10-27-200012-2.md").exists()
    log.abandon()
    assert [p.name for p in tmp_path.iterdir()] == [FIRST_NAME]
    assert (tmp_path / FIRST_NAME).read_text(encoding="utf-8") == "前回の配信"


def test_abandon_keeps_file_with_an_event(tmp_path: Path) -> None:
    log = open_log(tmp_path, FakeClock())
    log.effect("death")
    log.abandon()
    text = read(only_file(tmp_path))
    assert [row[2] for row in rows(text)] == ["死亡"]
    assert "- 死亡：1 回\n" in text  # close と同じく、まとめを書いて残す


def test_abandon_after_close_does_nothing(tmp_path: Path) -> None:
    log = open_log(tmp_path, FakeClock())
    log.close()
    log.abandon()
    assert "## まとめ" in read(only_file(tmp_path))


def test_abandon_only_warns_when_delete_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    log = open_log(tmp_path, FakeClock())

    def deny(*_: object, **__: object) -> None:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(Path, "unlink", deny)
    log.abandon()  # 例外にしない
    assert only_file(tmp_path).name == FIRST_NAME
    assert "消せませんでした" in caplog.text
    assert str(tmp_path) not in caplog.text


def test_abandon_does_not_delete_outside_output_dir(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # 作ったときのパスが output_dir の直下でなければ、消さない
    folder = tmp_path / "logs"
    folder.mkdir()
    outside = tmp_path / "outside.md"
    log = StreamLog(
        outside.open("x", encoding="utf-8", newline="\n"),
        path=outside,
        output_dir=folder,
        include_keyword=False,
        started=START,
        now=FakeClock().now,
        monotonic=FakeClock().monotonic,
    )
    log.abandon()
    assert outside.exists()
    assert "消しませんでした" in caplog.text


def test_main_success_keeps_log_without_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 起動できて終わったときは、できごとがなくてもまとめを書いて残す
    monkeypatch.setattr(server, "serve", lambda *a, **kw: None)
    monkeypatch.chdir(tmp_path)
    folder = tmp_path / "logs"
    folder.mkdir()
    assert main(["--config", str(write_log_config(tmp_path, folder))]) == 0
    text = read(only_file(folder))
    assert rows(text) == []
    assert "- 配信時間：" in text


# 設定


def test_include_speech_text_is_error_and_points_to_include_keyword(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text("[log]\ninclude_speech_text = true\n", encoding="utf-8")
    with pytest.raises(ConfigError) as e:
        load_config(config)
    message = str(e.value)
    assert "[log] include_speech_text" in message
    assert "廃止" in message
    assert "include_keyword" in message


def test_include_keyword_setting() -> None:
    assert LogConfig().include_keyword is False
    assert LogConfig(include_keyword=True).include_keyword is True
