"""マイクから音量 (dBFS) だけを取り出す。

プライバシーのため、次を守る。
- 音声のサンプルはコールバックの中で音量にしたら捨てる。リストやキューにためない
- 音声をファイルに残さない。外に送らない
sounddevice を直接呼ぶのは SoundDeviceBackend だけにし、テストでは偽物に差し替える。
"""

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np
from numpy.typing import NDArray

SAMPLE_RATE = 16_000
BLOCK_SIZE = 480  # 約 30 ms
BLOCK_SECONDS = BLOCK_SIZE / SAMPLE_RATE
SILENCE_DBFS = -100.0

type Samples = NDArray[np.float32]
type LevelCallback = Callable[[float], None]


class AudioError(Exception):
    """マイクを選べない・使えないときの例外。"""


@dataclass(frozen=True)
class InputDevice:
    index: int
    name: str
    host_api: str


class InputStream(Protocol):
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def close(self) -> None: ...


class AudioBackend(Protocol):
    def input_devices(self) -> list[InputDevice]: ...

    def create_stream(
        self, device: int | None, on_block: Callable[[Samples], None]
    ) -> InputStream: ...


def block_dbfs(samples: Samples) -> float:
    """1 ブロックの音量 (RMS、dBFS)。無音で計算できないときは SILENCE_DBFS。"""
    if samples.size == 0:
        return SILENCE_DBFS
    rms = math.sqrt(float(np.mean(np.square(samples, dtype=np.float64))))
    if not math.isfinite(rms) or rms <= 0.0:
        return SILENCE_DBFS
    return max(20.0 * math.log10(rms), SILENCE_DBFS)


def select_device(name: str, devices: Sequence[InputDevice]) -> int | None:
    """設定の audio.device からマイクを選ぶ。空なら None (OS の既定)。

    名前にその文字列を含む入力デバイスのうち、最初のものを選ぶ。
    """
    if not name:
        return None
    for device in devices:
        if name in device.name:
            return device.index
    listing = "\n".join(f"  {_display_name(d)}" for d in devices) or "  (入力デバイスがありません)"
    raise AudioError(
        f'[audio] device に指定した "{name}" を含む入力デバイスが見つかりません。\n'
        f"使える入力デバイス:\n{listing}"
    )


def format_devices(devices: Sequence[InputDevice]) -> str:
    if not devices:
        return "入力デバイスが見つかりません。"
    return "\n".join(f"{d.index}: {_display_name(d)} ({d.host_api})" for d in devices)


def _display_name(device: InputDevice) -> str:
    # デバイス名に改行が入っていることがあるので、表示では 1 行にまとめる
    return " ".join(device.name.split())


class Microphone:
    """マイクを開き、ブロックごとの音量だけを on_level に渡す。"""

    def __init__(self, backend: AudioBackend, device: int | None) -> None:
        self._on_level: LevelCallback | None = None
        self._closed = False
        self._stream = backend.create_stream(device, self._on_block)

    def _on_block(self, samples: Samples) -> None:
        # 音声のサンプルはここで音量にして、どこにも残さない
        on_level = self._on_level
        if on_level is not None:
            on_level(block_dbfs(samples[:, 0] if samples.ndim == 2 else samples))

    def start(self, on_level: LevelCallback) -> None:
        self._on_level = on_level
        self._stream.start()

    def close(self) -> None:
        """何度呼んでもよい。"""
        if self._closed:
            return
        self._closed = True
        self._on_level = None
        try:
            self._stream.stop()
        finally:
            self._stream.close()


class SoundDeviceBackend:
    """sounddevice (PortAudio) を使う本物のバックエンド。"""

    def input_devices(self) -> list[InputDevice]:
        sd = _sounddevice()
        host_apis = sd.query_hostapis()
        return [
            InputDevice(index, str(info["name"]), str(host_apis[info["hostapi"]]["name"]))
            for index, info in enumerate(sd.query_devices())
            if info["max_input_channels"] > 0
        ]

    def create_stream(self, device: int | None, on_block: Callable[[Samples], None]) -> InputStream:
        sd = _sounddevice()

        def callback(indata: Samples, _frames: int, _time: Any, _status: Any) -> None:
            on_block(indata)

        try:
            stream: InputStream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                blocksize=BLOCK_SIZE,
                channels=1,
                dtype="float32",
                device=device,
                callback=callback,
            )
        except sd.PortAudioError as e:
            raise AudioError(f"マイクを開けません: {e}") from None
        return stream


def default_backend() -> AudioBackend:
    return SoundDeviceBackend()


def _sounddevice() -> Any:
    # PortAudio の読み込みは実際に使うときだけ行う (テストでは呼ばれない)
    import sounddevice  # type: ignore[import-untyped]

    return sounddevice
