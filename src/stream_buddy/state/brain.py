"""4 つをまとめる Brain。状態機械どうしをつなぐのはここだけ。"""

from stream_buddy.state import constants as c
from stream_buddy.state.arbiter import Arbiter
from stream_buddy.state.event_fsm import EventMachine
from stream_buddy.state.events import (
    Effect,
    Hotkey,
    Input,
    Keyword,
    Mouth,
    Output,
    SpeechEnded,
    SpeechStarted,
    Tick,
)
from stream_buddy.state.silence import SilenceHunter
from stream_buddy.state.tension import Tension


class Brain:
    """入力を各状態機械に配り、出力を出口に通して返す。"""

    def __init__(self, start_ms: int, silence_seconds: int = c.DEFAULT_SILENCE_SECONDS) -> None:
        self.tension = Tension(start_ms)
        self.silence = SilenceHunter(start_ms, silence_seconds)
        self.event = EventMachine()
        self.arbiter = Arbiter()

    def step(self, event: Input, now_ms: int) -> list[Output]:
        # 前の step から今までが演出中だったか。演出中の時間は沈黙に数えない
        paused = self.event.state == "effecting"
        outputs: list[Output] = []
        match event:
            case SpeechStarted() | SpeechEnded():
                outputs.append(Mouth(speaking=isinstance(event, SpeechStarted)))
                outputs += self.tension.step(event, now_ms)
                outputs += self.silence.step(event, now_ms, paused=paused)
            case Keyword() | Hotkey():
                # 演出が始まる前までの沈黙を数えておく
                self.silence.advance(now_ms, paused=paused)
                outputs += self.event.step(event, now_ms)
                # 演出が始まったら、テンションに補正を伝える
                for effect in [o for o in outputs if isinstance(o, Effect)]:
                    outputs += self.tension.step(effect, now_ms)
            case Tick():
                outputs += self.event.step(event, now_ms)
                outputs += self.tension.step(event, now_ms)
                outputs += self.silence.step(event, now_ms, paused=paused)
        return self.arbiter.filter(outputs, now_ms)
