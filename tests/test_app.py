"""組み立て (入力 → Brain → セリフ → ページ) のテスト。

本物のマイク・Vosk・ホットキーは使わず、偽物と差し替えた時計で確かめる。
"""

import asyncio
import json
import random
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from conftest import FakeBackend, FakeHotkeyApi
from fastapi.testclient import TestClient

import stream_buddy.__main__ as main_module
from stream_buddy import app, demo, server
from stream_buddy.__main__ import main
from stream_buddy.audio import BLOCK_SIZE, Microphone
from stream_buddy.config import AudioConfig, Config, SilenceConfig
from stream_buddy.keywords import Grammar, KeywordSetup
from stream_buddy.lines import load_lines
from stream_buddy.protocol import SERVER_MESSAGE_TYPES, ServerMessage
from stream_buddy.state import events as ev

PORT = 8765
TOKEN = "test-token-0123456789"  # noqa: S105
BASE = f"http://127.0.0.1:{PORT}"
WS = f"ws://127.0.0.1:{PORT}"
ORIGIN = {"origin": BASE}
HELLO = '{"v": 0, "type": "hello", "payload": {"page_version": "0.1.0"}}'
TICK = 100


def rng(seed: int = 0) -> random.Random:
    return random.Random(seed)  # noqa: S311  テストで結果を固定するための乱数 (暗号用途ではない)


class Sim:
    """差し替えた時計で Engine を動かす。100 ms ごとに Tick を入れて、配信の流れを再現する。"""

    def __init__(self, silence_seconds: int = 20) -> None:
        self.now = 0
        config = Config(silence=SilenceConfig(seconds=silence_seconds))
        self.engine = app.Engine(config, load_lines(), clock=lambda: self.now, rng=rng())
        self.sent: list[tuple[int, ServerMessage]] = []

    async def _broadcast(self, message: ServerMessage) -> None:
        self.sent.append((self.now, message))

    def at(self, when: int, *events: ev.Input) -> None:
        """when まで時計を進め (100 ms ごとに Tick)、そこで events を入れる。"""
        asyncio.run(self._run(when, events))

    async def _run(self, when: int, events: Sequence[ev.Input]) -> None:
        while self.now + TICK <= when:
            self.now += TICK
            await self.engine.handle(ev.Tick(), self._broadcast)
        self.now = when
        for event in events:
            await self.engine.handle(event, self._broadcast)

    def of(self, kind: str) -> list[tuple[int, dict[str, Any]]]:
        return [(t, m.payload.model_dump()) for t, m in self.sent if m.type == kind]

    def says(self, prefix: str) -> list[int]:
        return [t for t, p in self.of("say") if p["line_id"].startswith(prefix)]


def talk(sim: Sim, start: int, end: int) -> None:
    sim.at(start, ev.SpeechStarted())
    sim.at(end, ev.SpeechEnded())


# 入力 → ページへのメッセージ


def test_speech_is_sent() -> None:
    sim = Sim()
    talk(sim, 1_000, 2_000)
    assert sim.of("speech") == [(1_000, {"speaking": True}), (2_000, {"speaking": False})]


def test_long_talk_raises_tension_and_says_high_line() -> None:
    sim = Sim()
    sim.at(0, ev.SpeechStarted())
    sim.at(30_000)
    assert sim.of("tension") == [(10_500, {"level": "normal"}), (21_000, {"level": "high"})]
    high_lines = sim.says("tension.high.")
    assert high_lines == [21_000]


def test_hotkey_clear_sends_effect_and_clear_line() -> None:
    sim = Sim()
    sim.at(1_000, ev.Hotkey("clear"))
    assert sim.of("effect") == [(1_000, {"kind": "clear"})]
    assert sim.says("event.clear.") == [1_000]


def test_keyword_death_sends_effect_and_line_and_ignores_repeat_within_5s() -> None:
    sim = Sim()
    sim.at(1_000, ev.Keyword("death"))
    sim.at(4_000, ev.Keyword("death"))  # 5 秒以内の同じ種類の 2 回目は無視
    sim.at(5_999, ev.Keyword("death"))
    sim.at(6_000, ev.Keyword("death"))  # 5 秒たてば受け付ける
    assert sim.of("effect") == [(1_000, {"kind": "death"}), (6_000, {"kind": "death"})]
    assert sim.says("event.death.") == [1_000, 6_000]


def test_keyword_of_other_kind_is_accepted_after_effect() -> None:
    sim = Sim()
    sim.at(1_000, ev.Keyword("clear"))
    sim.at(4_000, ev.Keyword("death"))  # 違う種類は演出が終われば受け付ける (ST-26)
    assert sim.of("effect") == [(1_000, {"kind": "clear"}), (4_000, {"kind": "death"})]
    assert sim.says("event.") == [1_000, 4_000]


@pytest.mark.parametrize("silence_seconds", [5, 20])
def test_silence_line_after_silence_seconds(silence_seconds: int) -> None:
    sim = Sim(silence_seconds)
    talk(sim, 0, 1_000)
    end = 1_000 + silence_seconds * 1000
    sim.at(end)
    assert sim.says("silence.") == []
    sim.at(end + TICK)
    # そのときのテンション (calm) の silence のセリフ
    assert sim.says("silence.calm.") == [end + TICK]


def test_silence_line_follows_current_tension() -> None:
    sim = Sim(silence_seconds=5)
    sim.at(0, ev.SpeechStarted())
    sim.at(12_000, ev.SpeechEnded())  # 盛り上がり度 40 → Normal
    sim.at(20_000)
    assert sim.engine.tension == "normal"
    assert sim.says("silence.normal.") == [17_100]


def test_all_sent_messages_are_valid_protocol_messages() -> None:
    sim = Sim(silence_seconds=5)
    sim.at(0, ev.SpeechStarted())
    sim.at(25_000, ev.SpeechEnded(), ev.Hotkey("clear"))
    sim.at(40_000, ev.Keyword("death"))
    sim.at(60_000)
    types = {m.type for _, m in sim.sent}
    assert types == {"speech", "tension", "say", "effect"}
    for _, message in sim.sent:
        assert isinstance(message, SERVER_MESSAGE_TYPES)
        assert type(message).model_validate_json(message.model_dump_json()) == message


def test_only_tension_peak_is_dropped() -> None:
    engine = Sim().engine
    outputs: list[ev.Output] = [
        ev.Mouth(speaking=True),
        ev.TensionChanged("high"),
        ev.Say("silence"),
        ev.Say("high"),
        ev.Say("death"),
        ev.Say("clear"),
        ev.Effect("clear"),
        ev.TensionPeak(),
    ]
    converted = [engine.to_message(o) for o in outputs]
    assert [m.type if m is not None else None for m in converted] == [
        "speech",
        "tension",
        "say",
        "say",
        "say",
        "say",
        "effect",
        None,
    ]


# ページが接続したとき


def test_hello_gets_display_and_current_tension() -> None:
    sim = Sim()
    sim.at(0, ev.SpeechStarted())
    sim.at(22_000)
    assert sim.engine.tension == "high"
    page = server.create_app(Config(), TOKEN, state_messages=sim.engine.state_messages)
    with (
        TestClient(page, base_url=BASE) as client,
        client.websocket_connect(f"{WS}/ws?token={TOKEN}", headers=ORIGIN) as ws,
    ):
        ws.send_text(HELLO)
        assert ws.receive_json()["type"] == "display"
        assert ws.receive_json() == {"v": 0, "type": "tension", "payload": {"level": "high"}}


# キュー


def test_queue_overflow_drops_and_keeps_running() -> None:
    config = Config()
    engine = app.Engine(config, load_lines(), rng=rng(), max_queue=3)
    sent: list[ServerMessage] = []

    async def broadcast(message: ServerMessage) -> None:
        sent.append(message)

    async def run() -> None:
        engine.bind(asyncio.get_running_loop())
        for _ in range(10):
            engine.submit(ev.Hotkey("clear"))
        assert engine.dropped == 7
        pump = asyncio.create_task(engine.pump(broadcast))
        await asyncio.sleep(0.05)
        # あふれたあとも止まらずに処理を続ける
        engine.submit(ev.SpeechStarted())
        await asyncio.sleep(0.05)
        pump.cancel()

    asyncio.run(run())
    assert engine.dropped == 7
    assert [m.type for m in sent].count("effect") == 1  # Cooldown 中のホットキーは演出が続く
    assert sent[-1].type == "speech"


def test_pump_keeps_running_after_an_error() -> None:
    engine = app.Engine(Config(), load_lines(), rng=rng())
    sent: list[ServerMessage] = []
    calls = 0

    async def flaky(message: ServerMessage) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("送れなかった")
        sent.append(message)

    async def run() -> None:
        engine.bind(asyncio.get_running_loop())
        pump = asyncio.create_task(engine.pump(flaky))
        engine.submit(ev.SpeechStarted())
        engine.submit(ev.SpeechEnded())
        await asyncio.sleep(0.05)
        pump.cancel()

    asyncio.run(run())
    assert [m.type for m in sent] == ["speech"]


def test_submit_threadsafe_before_bind_is_dropped_quietly() -> None:
    engine = Sim().engine
    engine.submit_threadsafe(ev.Hotkey("clear"))  # ループがまだない
    engine.submit(ev.Hotkey("clear"))


# Runtime (サーバーの中で動くもの)


def run_page(runtime: app.Runtime, engine: app.Engine) -> TestClient:
    page = server.create_app(
        Config(), TOKEN, running=runtime.run, state_messages=engine.state_messages
    )
    return TestClient(page, base_url=BASE)


def test_microphone_levels_reach_page_as_speech(fake_audio: FakeBackend) -> None:
    config = Config(audio=AudioConfig(speech_threshold_db=-40.0))
    engine = app.Engine(config, load_lines(), rng=rng())
    mic = Microphone(fake_audio, None)
    runtime = app.Runtime(engine, config, microphone=mic)
    with (
        run_page(runtime, engine) as client,
        client.websocket_connect(f"{WS}/ws?token={TOKEN}", headers=ORIGIN) as ws,
    ):
        stream = fake_audio.streams[0]
        assert stream.started

        def feed() -> None:
            # 本物と同じく、別のスレッドから音声のブロックを流す
            for amplitude in [0.1] * 5 + [0.0] * 10:
                stream.push_level(amplitude)

        thread = threading.Thread(target=feed)
        thread.start()
        thread.join()
        assert ws.receive_json() == {"v": 0, "type": "speech", "payload": {"speaking": True}}
        assert ws.receive_json() == {"v": 0, "type": "speech", "payload": {"speaking": False}}
    # サーバーの終了でストリームが閉じられる
    assert stream.closed


class FakeRecognizer:
    def __init__(self) -> None:
        self.calls = 0

    def AcceptWaveform(self, data: bytes) -> bool:
        self.calls += 1
        return self.calls == 2

    def Result(self) -> str:
        return json.dumps({"text": "死ん だ"})

    def PartialResult(self) -> str:
        return json.dumps({"partial": ""})


class FakeModel:
    def has_word(self, word: str) -> bool:
        return True

    def recognizer(self, grammar_json: str) -> FakeRecognizer:
        return FakeRecognizer()


def keyword_setup() -> KeywordSetup:
    grammar = Grammar({"death": ("死ん だ",), "clear": ("クリア",)}, ())
    return KeywordSetup(FakeModel(), grammar)


def test_keyword_reaches_page_and_threads_stop(fake_audio: FakeBackend) -> None:
    config = Config()
    engine = app.Engine(config, load_lines(), rng=rng())
    mic = Microphone(fake_audio, None)
    runtime = app.Runtime(engine, config, microphone=mic, keywords=keyword_setup())
    with (
        run_page(runtime, engine) as client,
        client.websocket_connect(f"{WS}/ws?token={TOKEN}", headers=ORIGIN) as ws,
    ):
        assert any(t.name == "keywords" for t in threading.enumerate())
        stream = fake_audio.streams[0]
        stream.push(np.zeros(BLOCK_SIZE, dtype=np.float32))
        stream.push(np.zeros(BLOCK_SIZE, dtype=np.float32))
        received = [ws.receive_json() for _ in range(2)]
        assert received[0] == {"v": 0, "type": "effect", "payload": {"kind": "death"}}
        assert received[1]["type"] == "say"
        assert received[1]["payload"]["line_id"].startswith("event.death.")
    # 終了で、認識用のスレッドが止まり、マイクが閉じる
    assert not any(t.name == "keywords" for t in threading.enumerate())
    assert stream.closed


def test_runtime_stops_all_tasks() -> None:
    config = Config()
    engine = app.Engine(config, load_lines(), rng=rng())
    runtime = app.Runtime(engine, config, demo=True)
    sent: list[ServerMessage] = []

    async def broadcast(message: ServerMessage) -> None:
        sent.append(message)

    async def run() -> set[asyncio.Task[Any]]:
        async with runtime.run(broadcast):
            await asyncio.sleep(0.25)
            assert len(asyncio.all_tasks()) == 4  # pump・時計・デモ・このテスト
        return asyncio.all_tasks()

    remaining = asyncio.run(run())
    assert len(remaining) == 1  # このテスト自身だけ
    # デモの最初の入力 (話し始め) が Brain を通ってページに届いている
    assert sent[0].type == "speech"


# 起動と終了 (__main__)


def test_main_registers_hotkeys_and_releases_on_exit(
    fake_hotkeys: list[FakeHotkeyApi],
    fake_audio: FakeBackend,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(server, "serve", lambda config, token, **kw: calls.append(kw))
    monkeypatch.chdir(tmp_path)
    assert main([]) == 0
    assert len(calls) == 1
    assert fake_hotkeys[0].registered == {1, 2}
    assert sorted(fake_hotkeys[0].unregistered) == [1, 2]
    assert fake_audio.streams[0].closed
    assert not any(t.name == "hotkeys" for t in threading.enumerate())


@pytest.mark.parametrize("error", [RuntimeError("サーバーが起動できない"), KeyboardInterrupt()])
def test_main_cleans_up_when_server_fails(
    fake_hotkeys: list[FakeHotkeyApi],
    fake_audio: FakeBackend,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    error: BaseException,
) -> None:
    def fail(*_: object, **__: object) -> None:
        raise error

    monkeypatch.setattr(server, "serve", fail)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(type(error)):
        main([])
    # 途中で失敗しても、ホットキーの登録が外れ、マイクが閉じる
    assert sorted(fake_hotkeys[0].unregistered) == [1, 2]
    assert fake_audio.streams[0].closed
    assert not any(t.name == "hotkeys" for t in threading.enumerate())


def test_main_releases_hotkeys_when_microphone_is_missing(
    fake_hotkeys: list[FakeHotkeyApi], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(server, "serve", lambda *a, **kw: None)
    config = tmp_path / "config.toml"
    config.write_text('[audio]\ndevice = "Blue Yeti"\n', encoding="utf-8")
    assert main(["--config", str(config)]) == 2
    assert sorted(fake_hotkeys[0].unregistered) == [1, 2]


def test_main_continues_without_hotkeys(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    class Busy(FakeHotkeyApi):
        def register_hotkey(self, hotkey_id: int, modifiers: int, vk: int) -> int:
            return 1409  # ほかのアプリが使っている

    monkeypatch.setattr(main_module.hotkey, "User32Api", Busy)
    calls: list[object] = []
    monkeypatch.setattr(server, "serve", lambda *a, **kw: calls.append(kw))
    monkeypatch.chdir(tmp_path)
    assert main([]) == 0
    assert len(calls) == 1
    err = capsys.readouterr().err
    assert "F9（death）はほかのアプリが使っている" in err
    assert "ホットキーなしで起動します" in err


def test_main_lines_error_does_not_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[object] = []
    monkeypatch.setattr(server, "serve", lambda *a, **kw: calls.append(kw))
    config = tmp_path / "config.toml"
    config.write_text("[lines]\nfile = 'C:\\\\nothing\\\\lines.toml'\n", encoding="utf-8")
    assert main(["--config", str(config)]) == 2
    assert calls == []
    assert "セリフ集を読み込めません" in capsys.readouterr().err


def test_main_prints_only_url_and_notices(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(server, "serve", lambda *a, **kw: None)
    monkeypatch.chdir(tmp_path)
    assert main([]) == 0
    out = capsys.readouterr().out
    assert "/overlay?token=" in out
    # セリフや発話の内容は出さない
    lines = load_lines()
    assert not any(text in out for texts in lines.lists.values() for text in texts)


# デモ


def test_demo_flow_reaches_high_clear_silence_and_death() -> None:
    sim = Sim(silence_seconds=20)
    for at, event in demo.demo_script(20):
        sim.at(at, event)
    sim.at(demo.cycle_ms(20))
    assert {"level": "high"} in [p for _, p in sim.of("tension")]
    assert {p["kind"] for _, p in sim.of("effect")} == {"death", "clear"}
    assert sim.says("tension.high.")
    assert sim.says("event.clear.")
    assert sim.says("event.death.")
    assert sim.says("silence.")
    # 約 1 分で繰り返す
    assert 50_000 <= demo.cycle_ms(20) <= 70_000


def test_demo_uses_silence_seconds() -> None:
    assert demo.cycle_ms(60) - demo.cycle_ms(20) == 40_000
    sim = Sim(silence_seconds=5)
    for at, event in demo.demo_script(5):
        sim.at(at, event)
    sim.at(demo.cycle_ms(5))
    assert sim.says("silence.")


def test_run_demo_submits_script_in_order_and_repeats() -> None:
    submitted: list[ev.Input] = []
    slept: list[float] = []
    script = demo.demo_script(20)

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)
        if len(submitted) >= len(script) * 2:
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(demo.run_demo(submitted.append, 20, sleep=fake_sleep))
    assert submitted[: len(script)] == [event for _, event in script]
    assert submitted[len(script) : len(script) * 2] == [event for _, event in script]
    assert sum(slept[: len(script) + 1]) * 1000 == pytest.approx(demo.cycle_ms(20))
