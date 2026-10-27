"""4 つをまとめる Brain。状態機械どうしをつなぐのはここだけ。"""

from dataclasses import dataclass

from stream_buddy.state import constants as c
from stream_buddy.state.arbiter import Arbiter
from stream_buddy.state.event_fsm import EventMachine, EventState
from stream_buddy.state.events import (
    Effect,
    Hotkey,
    Input,
    Keyword,
    Mouth,
    Output,
    SpeechEnded,
    SpeechStarted,
    TensionLevel,
    Tick,
)
from stream_buddy.state.silence import SilenceHunter, SilenceState
from stream_buddy.state.tension import Tension


@dataclass(frozen=True)
class Snapshot:
    """確認用に読み出した今の状態。"""

    score: float  # 盛り上がり度 (0〜100)
    speech_score: float  # 内訳: 話していた割合 * 100
    bonus: float  # 内訳: イベントの補正。0〜100 に収めた分を含め、speech_score + bonus = score
    tension: TensionLevel
    since_change_ms: int  # 前回テンションが変わってから (まだなら起動から) の時間
    silence_state: SilenceState
    silence_calls: int
    event_state: EventState


class Brain:
    """入力を各状態機械に配り、出力を出口に通して返す。"""

    def __init__(self, start_ms: int, silence_seconds: int) -> None:
        """silence_seconds は設定の silence.seconds (沈黙ハンターの最初の待ち時間)。"""
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

    def snapshot(self, now_ms: int) -> Snapshot:
        """今の状態を読み出す。状態は変えない (呼んでも呼ばなくても step の結果は同じ)。"""
        speech, bonus = self.tension.breakdown(now_ms)
        score = min(c.TENSION_MAX, max(c.TENSION_MIN, speech + bonus))
        return Snapshot(
            score=score,
            speech_score=speech,
            bonus=score - speech,
            tension=self.tension.level,
            since_change_ms=now_ms - self.tension.last_change_ms,
            silence_state=self.silence.state,
            silence_calls=self.silence.calls,
            event_state=self.event.state,
        )
