"""沈黙ハンター (ST-11〜ST-15、FR-05)。"""

from typing import Literal

from stream_buddy.state import constants as c
from stream_buddy.state.events import Output, Say, SpeechEnded, SpeechStarted, Tick

type SilenceInput = SpeechStarted | SpeechEnded | Tick
type SilenceState = Literal["listening", "waiting", "gave_up"]


class SilenceHunter:
    """黙っている時間を数え、待ち時間を超えたら話しかける。待ち時間は倍々、3 回で打ち止め。"""

    def __init__(self, start_ms: int, silence_seconds: int) -> None:
        self.first_wait_ms = silence_seconds * 1000
        # 起動直後は、最初に話し終わるまで数えない
        self.state: SilenceState = "listening"
        self.calls = 0
        self.wait_ms = self.first_wait_ms
        self.silent_ms = 0
        self._last_ms = start_ms

    def advance(self, now_ms: int, *, paused: bool = False) -> None:
        """前の呼び出しから今までの時間を数える。paused なら演出中だったので数えない。"""
        if self.state == "waiting" and not paused:
            self.silent_ms += now_ms - self._last_ms
        self._last_ms = now_ms

    def step(self, event: SilenceInput, now_ms: int, *, paused: bool = False) -> list[Output]:
        """paused は、前の呼び出しから今までが演出中だったか (演出中の時間は数えない)。"""
        self.advance(now_ms, paused=paused)
        match event:
            case SpeechEnded() if self.state == "listening":
                # ST-11
                self.state = "waiting"
                self.calls = 0
                self.wait_ms = self.first_wait_ms
                self.silent_ms = 0
            case SpeechStarted() if self.state in ("waiting", "gave_up"):
                # ST-12 / ST-15
                self.state = "listening"
            case Tick() if self.state == "waiting" and self.silent_ms > self.wait_ms:
                return self._call()
        return []

    def _call(self) -> list[Output]:
        # ST-13: 回数 +1、待ち時間を 2 倍にし、数え直す
        self.calls += 1
        self.wait_ms *= c.SILENCE_WAIT_MULTIPLIER
        self.silent_ms = 0
        if self.calls >= c.SILENCE_MAX_CALLS:
            # ST-14: 3 回目を話しかけたら、そのまま打ち止め
            self.state = "gave_up"
        return [Say("silence")]
