"""マイクから音量 (dBFS) を取り出し、キーワード検知用に音声のブロックを渡す。

プライバシーのため、次を守る。
- 音量の計算に使ったサンプルは、コールバックの中で捨てる
- キーワード検知には、上限つきのキュー (BlockQueue、最大 1 秒分) でだけ音声を渡す。
  いっぱいなら捨て、ためない
- 音声をファイルに残さない。外に送らない
sounddevice を直接呼ぶのは SoundDeviceBackend だけにし、テストでは偽物に差し替える。
"""

import math
import queue
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np
from numpy.typing import NDArray

SAMPLE_RATE = 16_000
BLOCK_SIZE = 480  # 約 30 ms
BLOCK_SECONDS = BLOCK_SIZE / SAMPLE_RATE
SILENCE_DBFS = -100.0
# キーワード検知に渡すキューの上限 (1 秒分を超えない)
MAX_QUEUE_BLOCKS = int(1.0 / BLOCK_SECONDS)

type Samples = NDArray[np.float32]
type LevelCallback = Callable[[float], None]
type SampleSink = Callable[[Samples], object]


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


class BlockQueue:
    """コールバックから認識用のスレッドへ音声のブロックを渡す、上限つきのキュー。

    いっぱいなら新しいブロックを捨てる (ためない)。取り出した側は、すぐに使って手元に残さない。
    """

    def __init__(self, max_blocks: int = MAX_QUEUE_BLOCKS) -> None:
        self._queue: queue.Queue[Samples] = queue.Queue(maxsize=max_blocks)
        self.dropped = 0

    def offer(self, samples: Samples) -> bool:
        """ブロックの複製を入れる。いっぱいなら捨てて False。"""
        # コールバックの配列は使い回されるので、複製を渡す
        try:
            self._queue.put_nowait(np.array(samples, dtype=np.float32, copy=True).reshape(-1))
        except queue.Full:
            self.dropped += 1
            return False
        return True

    def take(self, timeout: float) -> Samples | None:
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def size(self) -> int:
        return self._queue.qsize()

    def clear(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                return


class Microphone:
    """マイクを開き、ブロックごとの音量を on_level に渡す。

    set_sample_sink で受け取り手 (BlockQueue.offer) を決めたときだけ、音声のブロックも渡す。
    """

    def __init__(self, backend: AudioBackend, device: int | None) -> None:
        self._on_level: LevelCallback | None = None
        self._sample_sink: SampleSink | None = None
        self._closed = False
        self._stream = backend.create_stream(device, self._on_block)

    def _on_block(self, samples: Samples) -> None:
        mono = samples[:, 0] if samples.ndim == 2 else samples
        on_level = self._on_level
        if on_level is not None:
            on_level(block_dbfs(mono))
        sink = self._sample_sink
        if sink is not None:
            sink(mono)

    def set_sample_sink(self, sink: SampleSink | None) -> None:
        """キーワード検知に音声のブロックを渡す先。None なら渡さない。"""
        self._sample_sink = sink

    def start(self, on_level: LevelCallback) -> None:
        self._on_level = on_level
        self._stream.start()

    def close(self) -> None:
        """何度呼んでもよい。"""
        if self._closed:
            return
        self._closed = True
        self._on_level = None
        self._sample_sink = None
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
