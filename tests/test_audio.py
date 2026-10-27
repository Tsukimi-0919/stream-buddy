import ast
import math
from pathlib import Path

import numpy as np
import pytest
from conftest import FakeBackend

from stream_buddy import audio, server
from stream_buddy.__main__ import main
from stream_buddy.audio import (
    BLOCK_SECONDS,
    BLOCK_SIZE,
    MAX_QUEUE_BLOCKS,
    SAMPLE_RATE,
    SILENCE_DBFS,
    AudioError,
    BlockQueue,
    InputDevice,
    Microphone,
    block_dbfs,
    select_device,
)

SRC = Path(audio.__file__).parent
PORT = 8765
TOKEN = "test-token-0123456789"  # noqa: S105
BASE = f"http://127.0.0.1:{PORT}"
WS = f"ws://127.0.0.1:{PORT}"
ORIGIN = {"origin": BASE}


# 音量の計算


def test_silence_is_minus_100() -> None:
    assert block_dbfs(np.zeros(BLOCK_SIZE, dtype=np.float32)) == SILENCE_DBFS == -100.0


def test_empty_block_is_minus_100() -> None:
    assert block_dbfs(np.zeros(0, dtype=np.float32)) == -100.0


def test_full_scale_sine_is_about_minus_3() -> None:
    t = np.arange(BLOCK_SIZE) / SAMPLE_RATE
    sine = np.sin(2 * math.pi * 1000 * t).astype(np.float32)
    assert block_dbfs(sine) == pytest.approx(-3.01, abs=0.05)


def test_constant_amplitude_level() -> None:
    assert block_dbfs(np.full(BLOCK_SIZE, 0.1, dtype=np.float32)) == pytest.approx(-20.0, abs=0.01)


def test_very_quiet_is_clamped() -> None:
    assert block_dbfs(np.full(BLOCK_SIZE, 1e-9, dtype=np.float32)) == -100.0


def test_nan_is_treated_as_silence() -> None:
    assert block_dbfs(np.full(BLOCK_SIZE, np.nan, dtype=np.float32)) == -100.0


# マイクの選び方


DEVICES = [
    InputDevice(0, "Microsoft Sound Mapper - Input", "MME"),
    InputDevice(1, "マイク (USB Audio Device)", "MME"),
    InputDevice(2, "ステレオ ミキサー (Realtek)", "MME"),
    InputDevice(7, "マイク (USB Audio Device)", "Windows WASAPI"),
]


def test_empty_name_selects_default() -> None:
    assert select_device("", DEVICES) is None


def test_select_by_part_of_name() -> None:
    assert select_device("USB Audio", DEVICES) == 1
    assert select_device("Realtek", DEVICES) == 2


def test_unknown_name_lists_devices() -> None:
    with pytest.raises(AudioError) as exc:
        select_device("Blue Yeti", DEVICES)
    message = str(exc.value)
    assert "Blue Yeti" in message
    assert "マイク (USB Audio Device)" in message
    assert "ステレオ ミキサー (Realtek)" in message


def test_unknown_name_without_devices() -> None:
    with pytest.raises(AudioError, match="入力デバイスがありません"):
        select_device("USB", [])


def test_format_devices_shows_index_and_name() -> None:
    text = audio.format_devices(DEVICES)
    assert "1: マイク (USB Audio Device) (MME)" in text
    assert "7: マイク (USB Audio Device) (Windows WASAPI)" in text
    assert audio.format_devices([]) == "入力デバイスが見つかりません。"


def test_format_devices_keeps_one_line_per_device() -> None:
    text = audio.format_devices(
        [InputDevice(53, "ヘッドセット (Hands-Free%0\n;(Lights))", "WDM-KS")]
    )
    assert text == "53: ヘッドセット (Hands-Free%0 ;(Lights)) (WDM-KS)"


# Microphone (偽のストリーム)


def test_microphone_passes_only_levels(fake_audio: FakeBackend) -> None:
    mic = Microphone(fake_audio, 1)
    levels: list[float] = []
    mic.start(levels.append)
    stream = fake_audio.streams[0]
    assert stream.device == 1
    assert stream.started
    stream.push_level(0.1)
    stream.push(np.zeros(BLOCK_SIZE, dtype=np.float32))
    assert levels == [pytest.approx(-20.0, abs=0.01), -100.0]
    assert all(isinstance(level, float) for level in levels)


def test_microphone_close_is_idempotent(fake_audio: FakeBackend) -> None:
    mic = Microphone(fake_audio, None)
    mic.start(lambda _: None)
    mic.close()
    mic.close()
    stream = fake_audio.streams[0]
    assert stream.stopped
    assert stream.closed


def test_microphone_ignores_blocks_after_close(fake_audio: FakeBackend) -> None:
    mic = Microphone(fake_audio, None)
    levels: list[float] = []
    mic.start(levels.append)
    mic.close()
    fake_audio.streams[0].push_level(0.5)
    assert levels == []


def test_microphone_passes_blocks_only_to_sample_sink(fake_audio: FakeBackend) -> None:
    mic = Microphone(fake_audio, None)
    blocks: list[np.ndarray] = []
    mic.start(lambda _: None)
    fake_audio.streams[0].push_level(0.1)  # 受け取り手がなければ渡さない
    mic.set_sample_sink(blocks.append)
    fake_audio.streams[0].push_level(0.2)
    assert len(blocks) == 1
    assert blocks[0].shape == (BLOCK_SIZE,)
    mic.close()
    fake_audio.streams[0].push_level(0.3)  # 閉じたあとは渡さない
    assert len(blocks) == 1


# 認識用のキュー


def test_queue_holds_at_most_1_second() -> None:
    assert MAX_QUEUE_BLOCKS * BLOCK_SECONDS <= 1.0
    assert BlockQueue().size() == 0


def test_queue_drops_blocks_when_full() -> None:
    blocks = BlockQueue(max_blocks=3)
    block = np.zeros(BLOCK_SIZE, dtype=np.float32)
    results = [blocks.offer(block) for _ in range(100)]
    # いっぱいになったら捨てる。たまり続けない
    assert results == [True] * 3 + [False] * 97
    assert blocks.size() == 3
    assert blocks.dropped == 97


def test_queue_copies_blocks() -> None:
    blocks = BlockQueue()
    block = np.full((BLOCK_SIZE, 1), 0.5, dtype=np.float32)
    blocks.offer(block)
    block.fill(0.0)  # コールバックの配列は使い回される
    taken = blocks.take(0.1)
    assert taken is not None
    assert taken.shape == (BLOCK_SIZE,)
    assert float(taken[0]) == 0.5


def test_queue_take_times_out_and_clear_empties() -> None:
    blocks = BlockQueue()
    assert blocks.take(0.01) is None
    blocks.offer(np.zeros(BLOCK_SIZE, dtype=np.float32))
    blocks.clear()
    assert blocks.size() == 0


def test_microphone_to_queue_through_sink(fake_audio: FakeBackend) -> None:
    mic = Microphone(fake_audio, None)
    blocks = BlockQueue(max_blocks=2)
    mic.set_sample_sink(blocks.offer)
    mic.start(lambda _: None)
    for _ in range(10):
        fake_audio.streams[0].push_level(0.1)
    assert blocks.size() == 2
    assert blocks.dropped == 8


# 起動処理


def test_main_opens_selected_microphone_and_closes_it(
    fake_audio: FakeBackend, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(server, "serve", lambda config, token, **kw: calls.append(kw))
    config_path = tmp_path / "config.toml"
    config_path.write_text('[audio]\ndevice = "USB Audio"\n', encoding="utf-8")

    assert main(["--config", str(config_path)]) == 0

    assert len(calls) == 1
    assert fake_audio.streams[0].device == 1
    assert fake_audio.streams[0].closed


def test_main_closes_microphone_on_ctrl_c(
    fake_audio: FakeBackend, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def interrupted(*_: object, **__: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(server, "serve", interrupted)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(KeyboardInterrupt):
        main([])
    assert fake_audio.streams[0].closed


def test_main_demo_does_not_open_microphone(
    fake_audio: FakeBackend, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(server, "serve", lambda config, token, **kw: calls.append(kw))
    monkeypatch.chdir(tmp_path)
    assert main(["--demo"]) == 0
    assert len(calls) == 1
    assert fake_audio.streams == []


def test_main_unknown_device_exits_2_with_list(
    fake_audio: FakeBackend,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[object] = []
    monkeypatch.setattr(server, "serve", lambda *a, **kw: calls.append(kw))
    config_path = tmp_path / "config.toml"
    config_path.write_text('[audio]\ndevice = "Blue Yeti"\n', encoding="utf-8")

    assert main(["--config", str(config_path)]) == 2
    assert calls == []
    err = capsys.readouterr().err
    assert "Blue Yeti" in err
    assert "マイク (USB Audio Device)" in err


def test_main_list_devices(fake_audio: FakeBackend, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--list-devices"]) == 0
    out = capsys.readouterr().out
    assert "1: マイク (USB Audio Device) (MME)" in out
    assert fake_audio.streams == []


# 音声を残さないことの検査 (文字列)


@pytest.mark.parametrize("module", ["audio.py", "detect.py", "keywords.py"])
@pytest.mark.parametrize("forbidden", ["wave", "soundfile", "write"])
def test_no_audio_file_output(module: str, forbidden: str) -> None:
    assert forbidden not in (SRC / module).read_text(encoding="utf-8")


@pytest.mark.parametrize("module", ["audio.py", "detect.py"])
def test_no_file_open(module: str) -> None:
    # keywords.py はハッシュ確認の読み込みだけ許す (test_keywords.py で検査する)
    assert "open(" not in (SRC / module).read_text(encoding="utf-8")


@pytest.mark.parametrize("module", ["audio.py", "detect.py"])
def test_imports_are_limited(module: str) -> None:
    tree = ast.parse((SRC / module).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    allowed = {"math", "queue", "collections", "dataclasses", "typing", "numpy", "sounddevice"}
    assert imported <= allowed


def test_detect_does_not_handle_audio_or_network() -> None:
    tree = ast.parse((SRC / "detect.py").read_text(encoding="utf-8"))
    names = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert names == {"math"}
