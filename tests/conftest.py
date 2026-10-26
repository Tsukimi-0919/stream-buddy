from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest

from stream_buddy import audio
from stream_buddy.audio import InputDevice, Samples


@pytest.fixture(autouse=True)
def local_app_data(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """すべてのテストで LOCALAPPDATA を一時フォルダに差し替え、実際の場所には書かない。"""
    path = tmp_path_factory.mktemp("localappdata")
    monkeypatch.setenv("LOCALAPPDATA", str(path))
    return path


class FakeStream:
    """偽の入力ストリーム。push で音声のブロックをコールバックに流し込む。"""

    def __init__(self, device: int | None, on_block: Callable[[Samples], None]) -> None:
        self.device = device
        self.on_block = on_block
        self.started = False
        self.stopped = False
        self.closed = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def close(self) -> None:
        self.closed = True

    def push(self, block: Samples) -> None:
        self.on_block(block.reshape(-1, 1))

    def push_level(self, amplitude: float) -> None:
        """振幅が一定のブロックを流す (音量は 20*log10(amplitude) dBFS)。"""
        self.push(np.full(audio.BLOCK_SIZE, amplitude, dtype=np.float32))


class FakeBackend:
    """本物のマイクの代わり。CI にはマイクがないため、テストではすべてこれを使う。"""

    def __init__(self, devices: list[InputDevice] | None = None) -> None:
        self.devices = (
            devices
            if devices is not None
            else [
                InputDevice(0, "Microsoft Sound Mapper - Input", "MME"),
                InputDevice(1, "マイク (USB Audio Device)", "MME"),
                InputDevice(5, "マイク (USB Audio Device)", "Windows WASAPI"),
            ]
        )
        self.streams: list[FakeStream] = []

    def input_devices(self) -> list[InputDevice]:
        return list(self.devices)

    def create_stream(self, device: int | None, on_block: Callable[[Samples], None]) -> FakeStream:
        stream = FakeStream(device, on_block)
        self.streams.append(stream)
        return stream


@pytest.fixture(autouse=True)
def fake_audio(monkeypatch: pytest.MonkeyPatch) -> FakeBackend:
    """すべてのテストで本物のマイク (sounddevice) を使わないようにする。"""
    backend = FakeBackend()
    monkeypatch.setattr(audio, "default_backend", lambda: backend)
    return backend


@pytest.fixture(autouse=True)
def no_real_model(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """すべてのテストで本物の音声認識モデルを使わないよう、既定のモデルの場所をない場所にする。"""
    from stream_buddy import keywords

    missing = tmp_path_factory.mktemp("no-model") / "models" / keywords.MODEL_NAME
    monkeypatch.setattr(keywords, "default_model_dir", lambda: missing)
    return missing
