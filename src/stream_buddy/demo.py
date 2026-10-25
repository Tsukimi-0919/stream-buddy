"""見え方を確認するためのデモモード (`stream-buddy --demo`)。"""

import asyncio
from collections.abc import Awaitable, Callable

from stream_buddy.protocol import (
    Say,
    SayPayload,
    ServerMessage,
    Speech,
    SpeechPayload,
    Tension,
    TensionPayload,
)

# メッセージを送る間隔 (秒)
DEMO_INTERVAL_SECONDS = 2.5

DEMO_LINE_CALM = "ふむふむ、いい感じだね～"  # noqa: RUF001
DEMO_LINE_HIGH = "うおおお！"  # noqa: RUF001

DEMO_STEPS: tuple[ServerMessage, ...] = (
    # 1. 落ち着いて少ししゃべる
    Tension(payload=TensionPayload(level="calm")),
    Speech(payload=SpeechPayload(speaking=True)),
    Speech(payload=SpeechPayload(speaking=False)),
    # 2. ふつう
    Tension(payload=TensionPayload(level="normal")),
    Say(payload=SayPayload(line_id="demo-normal", text=DEMO_LINE_CALM)),
    # 3. 盛り上がる
    Tension(payload=TensionPayload(level="high")),
    Speech(payload=SpeechPayload(speaking=True)),
    Say(payload=SayPayload(line_id="demo-high", text=DEMO_LINE_HIGH)),
    Speech(payload=SpeechPayload(speaking=False)),
)


async def run_demo(broadcast: Callable[[ServerMessage], Awaitable[None]]) -> None:
    """デモの流れを止められるまで繰り返し送る。"""
    while True:
        for message in DEMO_STEPS:
            await broadcast(message)
            await asyncio.sleep(DEMO_INTERVAL_SECONDS)
