"""組み立て: 入力 → 状態機械 (Brain) → セリフ → OBS のページ。

- すべての入力 (発話・キーワード・ホットキー・時計の Tick) を、asyncio のループの中の
  1 つのキューに集める。スレッドからは call_soon_threadsafe で入れる
- キューから取り出して Brain.step を呼ぶのは、1 つのタスク (pump) だけ
- 発話の内容・認識した文字列・セリフ選びの途中経過は、ログにもコンソールにも出さない
"""

import asyncio
import contextlib
import logging
import random
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import assert_never

from stream_buddy import demo as demo_mode
from stream_buddy.audio import BLOCK_SECONDS, BlockQueue, Microphone
from stream_buddy.config import Config
from stream_buddy.detect import SpeechDetector
from stream_buddy.keywords import KeywordListener, KeywordSetup
from stream_buddy.lines import LineBook, LinePicker
from stream_buddy.protocol import (
    Effect,
    EffectPayload,
    Say,
    SayPayload,
    ServerMessage,
    Speech,
    SpeechPayload,
    Tension,
    TensionPayload,
)
from stream_buddy.state import constants
from stream_buddy.state import events as ev
from stream_buddy.state.brain import Brain

MAX_QUEUE = 1000
_DROP_WARNING_EVERY = 100

type Clock = Callable[[], int]
type Broadcast = Callable[[ServerMessage], Awaitable[None]]

logger = logging.getLogger(__name__)


def monotonic_ms() -> int:
    return int(time.monotonic() * 1000)


class Engine:
    """入力のキューと Brain、出力からページへのメッセージへの変換を受け持つ。"""

    def __init__(
        self,
        config: Config,
        book: LineBook,
        *,
        clock: Clock = monotonic_ms,
        rng: random.Random | None = None,
        max_queue: int = MAX_QUEUE,
    ) -> None:
        self._silence_seconds = config.silence.seconds
        self._clock = clock
        self._picker = LinePicker(book, rng if rng is not None else random.Random())  # noqa: S311  セリフ選び (暗号用途ではない)
        self._max_queue = max_queue
        self.brain = Brain(start_ms=clock(), silence_seconds=self._silence_seconds)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: asyncio.Queue[ev.Input] | None = None
        self.dropped = 0

    # 入力

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        """ループの中で入力を受け付け始める。Brain の時刻はここから数える。"""
        self._loop = loop
        self._queue = asyncio.Queue(maxsize=self._max_queue)
        self.brain = Brain(start_ms=self._clock(), silence_seconds=self._silence_seconds)

    def unbind(self) -> None:
        self._loop = None

    def submit(self, event: ev.Input) -> None:
        """ループの中から入力を入れる。いっぱいなら捨てて数える。"""
        if self._queue is None:
            return
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            self.dropped += 1
            if self.dropped % _DROP_WARNING_EVERY == 1:
                # 中身は出さず、数だけを残す
                logger.warning("入力が多すぎるため捨てました（合計 %d 件）", self.dropped)

    def submit_threadsafe(self, event: ev.Input) -> None:
        """ほかのスレッドから入力を入れる。ループが動いていなければ捨てる。"""
        loop = self._loop
        if loop is None:
            return
        with contextlib.suppress(RuntimeError):  # 終了処理中でループが閉じている
            loop.call_soon_threadsafe(self.submit, event)

    # 処理

    async def pump(self, broadcast: Broadcast) -> None:
        """キューから取り出して Brain に通す。これを呼ぶタスクは 1 つだけにする。"""
        queue = self._queue
        if queue is None:
            raise RuntimeError("bind の前に pump は始められません")
        while True:
            event = await queue.get()
            try:
                await self.handle(event, broadcast)
            except Exception:
                # 1 つの入力で失敗しても、メンダコが止まらないように続ける (入力の中身は出さない)
                logger.exception("入力の処理中にエラーが起きました（処理は続けます）")

    async def handle(self, event: ev.Input, broadcast: Broadcast) -> None:
        """1 つの入力を Brain に通し、出力をページに送る。時刻は取り出したときに付ける。"""
        for output in self.brain.step(event, self._clock()):
            message = self.to_message(output)
            if message is not None:
                await broadcast(message)

    def to_message(self, output: ev.Output) -> ServerMessage | None:
        match output:
            case ev.Mouth(speaking):
                return Speech(payload=SpeechPayload(speaking=speaking))
            case ev.TensionChanged(level):
                return Tension(payload=TensionPayload(level=level))
            case ev.Say(situation):
                line_id, text = self._picker.pick(situation, self.tension)
                return Say(payload=SayPayload(line_id=line_id, text=text))
            case ev.Effect(kind):
                return Effect(payload=EffectPayload(kind=kind))
            case ev.TensionPeak():
                return None  # 配信ログ (Phase 3) で使う。今は送らない
            case _:
                assert_never(output)

    @property
    def tension(self) -> ev.TensionLevel:
        return self.brain.tension.level

    def state_messages(self) -> list[ServerMessage]:
        """接続したページに送る、今の状態。"""
        return [Tension(payload=TensionPayload(level=self.tension))]


async def run_clock(submit: Callable[[ev.Input], None]) -> None:
    """100 ms ごとに Tick を入れる。"""
    while True:
        await asyncio.sleep(constants.TICK_MS / 1000)
        submit(ev.Tick())


class Runtime:
    """サーバーが動いている間に動かすもの。起動の 7・8 番目と、その逆順の終了を受け持つ。

    7. マイクを開き (始め)、認識用のスレッドを始める
    8. 時計と、キューを処理するタスクを始める
    """

    def __init__(
        self,
        engine: Engine,
        config: Config,
        *,
        microphone: Microphone | None = None,
        keywords: KeywordSetup | None = None,
        demo: bool = False,
    ) -> None:
        self.engine = engine
        self._threshold_db = config.audio.speech_threshold_db
        self._silence_seconds = config.silence.seconds
        self._microphone = microphone
        self._keywords = keywords
        self._demo = demo

    @contextlib.asynccontextmanager
    async def run(self, broadcast: Broadcast) -> AsyncIterator[None]:
        engine = self.engine
        engine.bind(asyncio.get_running_loop())
        async with contextlib.AsyncExitStack() as stack:
            stack.callback(engine.unbind)
            if self._microphone is not None:
                self._start_microphone(self._microphone, stack)
            for task in self._tasks(broadcast):
                stack.push_async_callback(_cancel, task)
            yield

    def _start_microphone(self, microphone: Microphone, stack: contextlib.AsyncExitStack) -> None:
        engine = self.engine
        detector = SpeechDetector(self._threshold_db, BLOCK_SECONDS)

        def on_level_in_loop(level_db: float) -> None:
            changed = detector.update(level_db)
            if changed is not None:
                engine.submit(ev.SpeechStarted() if changed else ev.SpeechEnded())

        loop = asyncio.get_running_loop()

        def on_level(level_db: float) -> None:
            # 音声のスレッドから呼ばれる。渡すのは音量の数値だけ
            with contextlib.suppress(RuntimeError):  # 終了処理中でループが閉じている
                loop.call_soon_threadsafe(on_level_in_loop, level_db)

        # 閉じるのは最後 (コールバックは後入れ先出しで呼ばれる)
        stack.callback(microphone.close)
        if self._keywords is not None:
            blocks = BlockQueue()
            listener = KeywordListener(
                self._keywords.spotter(),
                blocks,
                # 認識用のスレッドから呼ばれる。渡すのはキーワードの種類だけ
                lambda kind: engine.submit_threadsafe(ev.Keyword(kind)),
            )
            microphone.set_sample_sink(blocks.offer)
            listener.start()
            stack.callback(listener.stop)
            stack.callback(microphone.set_sample_sink, None)
        microphone.start(on_level)

    def _tasks(self, broadcast: Broadcast) -> list[asyncio.Task[None]]:
        engine = self.engine
        tasks = [
            asyncio.create_task(engine.pump(broadcast)),
            asyncio.create_task(run_clock(engine.submit)),
        ]
        if self._demo:
            tasks.append(
                asyncio.create_task(demo_mode.run_demo(engine.submit, self._silence_seconds))
            )
        return tasks


async def _cancel(task: asyncio.Task[None]) -> None:
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
