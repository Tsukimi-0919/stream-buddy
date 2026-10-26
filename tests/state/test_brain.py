"""Brain を通したシナリオテスト。100 ms ごとに tick を入れて、配信の流れを再現する。"""

from stream_buddy.state.brain import Brain
from stream_buddy.state.events import (
    Effect,
    Hotkey,
    Input,
    Keyword,
    Mouth,
    Output,
    Say,
    SpeechEnded,
    SpeechStarted,
    TensionChanged,
    TensionPeak,
    Tick,
)

TICK = 100


class Sim:
    def __init__(self, silence_seconds: int = 20) -> None:
        self.brain = Brain(start_ms=0, silence_seconds=silence_seconds)
        self.now = 0
        self.log: list[tuple[int, Output]] = []

    def until(self, end: int) -> None:
        """end まで tick を入れる (end を含む)。"""
        while self.now + TICK <= end:
            self.now += TICK
            self._feed(Tick())

    def at(self, when: int, event: Input) -> None:
        self.until(when)
        assert self.now == when
        self._feed(event)

    def _feed(self, event: Input) -> None:
        self.log += [(self.now, o) for o in self.brain.step(event, self.now)]

    def of(self, kind: type) -> list[tuple[int, Output]]:
        return [(t, o) for t, o in self.log if isinstance(o, kind)]


def test_mouth_follows_speech() -> None:
    sim = Sim()
    sim.at(1_000, SpeechStarted())
    sim.at(2_000, SpeechEnded())
    assert sim.of(Mouth) == [(1_000, Mouth(speaking=True)), (2_000, Mouth(speaking=False))]


def test_scenario_st01_st03_st04_st02_st13_talk_clear_high_then_silence() -> None:
    """話して盛り上がる → クリア → High → 黙る → 沈黙ハンター。"""
    sim = Sim()
    sim.at(0, SpeechStarted())
    sim.at(15_000, SpeechEnded())
    sim.at(16_000, Keyword("clear"))
    sim.until(40_000)

    assert sim.of(TensionChanged) == [
        (10_500, TensionChanged("normal")),  # ST-01: 10.5 秒話して 35
        (16_100, TensionChanged("high")),  # ST-03: 50 + クリアの補正
        (30_100, TensionChanged("normal")),  # ST-04: 補正が消え、窓から話した時間が抜けて 50 未満
        (39_100, TensionChanged("calm")),  # ST-02: 20 未満
    ]
    assert sim.of(TensionPeak) == [(16_100, TensionPeak())]
    assert sim.of(Effect) == [(16_000, Effect("clear"))]
    # Say(high) はクリアの吹き出しから 5 秒たっていないので捨てられる。
    # 沈黙は 15 秒から数え、演出中の 3 秒 (16〜19 秒) を除いて 20 秒を超えた 38.1 秒で話しかける
    assert sim.of(Say) == [(16_000, Say("clear")), (38_100, Say("silence"))]


def test_scenario_st21_st25_st24_st22_st23_death_then_hotkey() -> None:
    """死亡 → 連続のキーワードは無視 → ホットキーでクリア → 黙る。"""
    sim = Sim()
    sim.at(0, SpeechStarted())
    sim.at(12_000, SpeechEnded())
    sim.at(20_000, Keyword("death"))  # ST-21
    sim.at(21_000, Keyword("death"))  # ST-25: 演出中は無視
    sim.at(22_000, Hotkey("clear"))  # ST-25: ホットキーも無視
    sim.at(24_000, Keyword("death"))  # ST-22 のあと、Cooldown のキーワードは無視
    sim.at(25_000, Hotkey("clear"))  # ST-24: Cooldown 中のホットキーは受け付ける
    sim.until(45_000)  # ST-23: 35 秒で Ready に戻る

    assert sim.brain.event.state == "ready"
    assert sim.of(Effect) == [(20_000, Effect("death")), (25_000, Effect("clear"))]
    assert sim.of(TensionChanged) == [
        (10_500, TensionChanged("normal")),
        (20_100, TensionChanged("calm")),  # 死亡の減点 (40 から 30 引いた前後)
        (25_100, TensionChanged("normal")),  # クリアの加点。前の変化からちょうど 5 秒
        (36_100, TensionChanged("calm")),
    ]
    # 沈黙は 12 秒から。演出中 (20〜23 秒、25〜28 秒) を除いて 20 秒を超えた 38.1 秒で話しかける
    assert sim.of(Say) == [
        (20_000, Say("death")),
        (25_000, Say("clear")),
        (38_100, Say("silence")),
    ]


def test_scenario_st11_st13_st14_st15_silence_gives_up_and_restarts() -> None:
    sim = Sim()
    sim.until(60_000)
    assert sim.of(Say) == []  # 起動直後は数えない
    sim.at(60_000, SpeechStarted())
    sim.at(61_000, SpeechEnded())  # ST-11
    sim.until(300_000)
    # ST-13 を 3 回、ST-14 で打ち止め
    assert sim.of(Say) == [
        (81_100, Say("silence")),
        (121_200, Say("silence")),
        (201_300, Say("silence")),
    ]
    assert sim.brain.silence.state == "gave_up"
    sim.at(300_000, SpeechStarted())  # ST-15
    sim.at(301_000, SpeechEnded())
    sim.until(330_000)
    assert sim.of(Say)[-1] == (321_100, Say("silence"))


def test_silence_seconds_comes_from_argument() -> None:
    sim = Sim(silence_seconds=5)
    sim.at(0, SpeechStarted())
    sim.at(1_000, SpeechEnded())
    sim.until(7_000)
    assert sim.of(Say) == [(6_100, Say("silence"))]
