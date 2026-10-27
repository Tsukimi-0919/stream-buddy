"""Brain を通したシナリオテスト。100 ms ごとに tick を入れて、配信の流れを再現する。"""

from stream_buddy.state.brain import Brain, Snapshot
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
    def __init__(self, silence_seconds: int) -> None:
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
    sim = Sim(silence_seconds=20)
    sim.at(1_000, SpeechStarted())
    sim.at(2_000, SpeechEnded())
    assert sim.of(Mouth) == [(1_000, Mouth(speaking=True)), (2_000, Mouth(speaking=False))]


def test_scenario_st01_st03_st04_st02_st13_talk_clear_high_then_silence() -> None:
    """話して盛り上がる → クリア → High → 黙る → 沈黙ハンター。"""
    sim = Sim(silence_seconds=20)
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
    # Say(high) はクリアの吹き出しから 3 秒たっていないので捨てられる。
    # 沈黙は 15 秒から数え、演出中の 3 秒 (16〜19 秒) を除いて 20 秒を超えた 38.1 秒で話しかける
    assert sim.of(Say) == [(16_000, Say("clear")), (38_100, Say("silence"))]


def test_scenario_st21_st25_st24_st22_st23_death_then_hotkey() -> None:
    """死亡 → 連続のキーワードは無視 → ホットキーでクリア → 黙る。"""
    sim = Sim(silence_seconds=20)
    sim.at(0, SpeechStarted())
    sim.at(12_000, SpeechEnded())
    sim.at(20_000, Keyword("death"))  # ST-21
    sim.at(21_000, Keyword("death"))  # ST-25: 演出中は無視
    sim.at(22_000, Hotkey("clear"))  # ST-25: ホットキーも無視
    sim.at(24_000, Keyword("death"))  # ST-22 のあと、5 秒以内の同じ種類のキーワードは無視
    sim.at(25_000, Hotkey("clear"))  # ST-24: Cooldown 中のホットキーは受け付ける
    sim.until(45_000)  # ST-23: 30 秒で Ready に戻る

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
    sim = Sim(silence_seconds=20)
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


# snapshot (確認用の読み出し)

# 話す・クリア・死亡・黙るを含む流れ (補正が 0〜100 からはみ出す時刻も含む)
SNAPSHOT_SCRIPT: list[tuple[int, Input]] = [
    (0, SpeechStarted()),
    (25_000, Keyword("clear")),  # 83 + 30 で 100 を超える
    (28_000, SpeechEnded()),
    (40_000, Hotkey("death")),
    (60_000, SpeechStarted()),
    (61_000, SpeechEnded()),
]


def run_script(snapshot_every: int | None) -> tuple[list[tuple[int, Output]], list[Snapshot]]:
    sim = Sim(silence_seconds=20)
    snapshots: list[Snapshot] = []
    script = list(SNAPSHOT_SCRIPT)
    while sim.now < 120_000:
        if script and script[0][0] == sim.now:
            sim._feed(script.pop(0)[1])
        if snapshot_every is not None and sim.now % snapshot_every == 0:
            # 同じ時刻に 2 回読んでも状態は変わらない
            snapshots += [sim.brain.snapshot(sim.now), sim.brain.snapshot(sim.now)]
        sim.until(sim.now + TICK)
    return sim.log, snapshots


def test_snapshot_does_not_change_step_results() -> None:
    without, _ = run_script(snapshot_every=None)
    with_snapshots, snapshots = run_script(snapshot_every=TICK)
    assert with_snapshots == without
    assert snapshots[0::2] == snapshots[1::2]


def test_snapshot_breakdown_adds_up_to_score() -> None:
    _, snapshots = run_script(snapshot_every=TICK)
    assert any(s.bonus > 0 for s in snapshots)
    assert any(s.bonus < 0 for s in snapshots)
    assert any(s.score == 100 for s in snapshots)  # 100 に収めた時刻も含む
    for s in snapshots:
        assert s.speech_score + s.bonus == s.score
        assert 0 <= s.score <= 100


def test_snapshot_matches_tension_score() -> None:
    sim = Sim(silence_seconds=20)
    sim.at(0, SpeechStarted())
    sim.at(12_000, SpeechEnded())
    snap = sim.brain.snapshot(15_000)
    assert snap.score == sim.brain.tension.score(15_000) == 40
    assert (snap.speech_score, snap.bonus) == (40, 0)


def test_snapshot_reports_states() -> None:
    sim = Sim(silence_seconds=20)
    first = sim.brain.snapshot(0)
    assert (first.tension, first.since_change_ms) == ("calm", 0)
    assert (first.silence_state, first.silence_calls, first.event_state) == (
        "listening",
        0,
        "ready",
    )
    sim.at(0, SpeechStarted())
    sim.at(12_000, SpeechEnded())  # 10.5 秒で Normal
    snap = sim.brain.snapshot(12_000)
    assert (snap.tension, snap.since_change_ms) == ("normal", 1_500)
    assert (snap.silence_state, snap.silence_calls) == ("waiting", 0)
    sim.at(13_000, Hotkey("clear"))
    assert sim.brain.snapshot(13_000).event_state == "effecting"
    assert sim.brain.snapshot(16_000).event_state == "effecting"  # 読むだけでは進めない
    sim.until(16_000)
    assert sim.brain.snapshot(16_000).event_state == "cooldown"
    # 沈黙は 12 秒から、演出中の 3 秒を除いて 20 秒を超えた 35.1 秒で 1 回話しかける
    sim.until(35_000)
    assert sim.brain.snapshot(35_000).silence_calls == 0
    sim.until(35_100)
    assert sim.of(Say)[-1] == (35_100, Say("silence"))
    assert sim.brain.snapshot(35_100).silence_calls == 1
