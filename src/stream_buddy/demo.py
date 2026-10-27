"""見え方を確認するためのデモモード (`stream-buddy --demo`)。

偽の入力を Brain に入れる。デモでも本物の状態機械とセリフ選びが動く。
マイク・音声認識・ホットキーは使わない。
"""

import asyncio
from collections.abc import Awaitable, Callable

from stream_buddy.state import events as ev

# 流れ (時間はすべてミリ秒。既定の silence.seconds = 20 で約 1 分)
# 1. 話す・止まるを繰り返して盛り上がり度を上げ、Normal → High にする
TALK_BURSTS = 7
TALK_MS = 3_500
PAUSE_MS = 500
# 2. ホットキーでクリア
CLEAR_AFTER_TALK_MS = 2_000
# 3. 少し話してから黙り、沈黙ハンターが話しかけるのを待つ (silence.seconds の設定を使う)
SHORT_TALK_MS = 2_000
SILENCE_MARGIN_MS = 1_000
# 4. キーワードで死亡
DEATH_AFTER_SILENCE_MS = 2_000
# 次の繰り返しまでの間
REST_MS = 3_000

type Step = tuple[int, ev.Input]  # (流れの始まりからの時刻, 入力)


def demo_script(silence_seconds: int) -> list[Step]:
    """1 回分の流れ。時刻は流れの始まりからのミリ秒で、昇順。"""
    steps: list[Step] = []
    t = 0
    for _ in range(TALK_BURSTS):
        steps += [(t, ev.SpeechStarted()), (t + TALK_MS, ev.SpeechEnded())]
        t += TALK_MS + PAUSE_MS
    t += CLEAR_AFTER_TALK_MS
    steps.append((t, ev.Hotkey("clear")))
    t += 1_000
    steps += [(t, ev.SpeechStarted()), (t + SHORT_TALK_MS, ev.SpeechEnded())]
    t += SHORT_TALK_MS + silence_seconds * 1000 + SILENCE_MARGIN_MS
    t += DEATH_AFTER_SILENCE_MS
    steps.append((t, ev.Keyword("death")))
    return steps


def cycle_ms(silence_seconds: int) -> int:
    """1 回分の流れの長さ。"""
    return demo_script(silence_seconds)[-1][0] + REST_MS


async def run_demo(
    submit: Callable[[ev.Input], None],
    silence_seconds: int,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """デモの流れを、止められるまで繰り返し入れる。"""
    script = demo_script(silence_seconds)
    length = cycle_ms(silence_seconds)
    while True:
        now = 0
        for at, event in script:
            await sleep((at - now) / 1000)
            now = at
            submit(event)
        await sleep((length - now) / 1000)
