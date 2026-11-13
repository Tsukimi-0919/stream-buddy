"""話していた割合を数えるときの、短い間のつなぎ (T-23、TENSION_GAP_BRIDGE_MS)。

発話の検知は 0.3 秒で話し終わりになるため、息継ぎや文の切れ目で細かく区切られる。
テンションの「話した割合」を数えるときだけ、1.0 秒未満の間は話していたとみなす。
口パクと沈黙ハンターは、今までどおり話し始め・話し終わりですぐ動く。
"""

import pytest

from stream_buddy.state import constants as c
from stream_buddy.state.brain import Brain
from stream_buddy.state.events import (
    Mouth,
    Output,
    Say,
    SpeechEnded,
    SpeechStarted,
    TensionChanged,
    TensionLevel,
    Tick,
)
from stream_buddy.state.tension import Tension

TICK = c.TICK_MS


def talk_in_bursts(t: Tension, talk_ms: int, gap_ms: int, until: int) -> None:
    """0 秒から、talk_ms 話して gap_ms 黙るのを until まで繰り返す (until では話している最中)。"""
    now = 0
    while now < until:
        t.step(SpeechStarted(), now)
        end = min(now + talk_ms, until)
        if end < until:
            t.step(SpeechEnded(), end)
        now = end + gap_ms


def speech(t: Tension, now_ms: int) -> float:
    return t.breakdown(now_ms)[0]


def test_bridge_is_1s() -> None:
    assert c.TENSION_GAP_BRIDGE_MS == 1_000


def test_talking_with_half_second_gaps_counts_as_almost_100() -> None:
    t = Tension(start_ms=0)
    # 2.5 秒話して 0.5 秒の息継ぎ、を 30 秒続ける
    talk_in_bursts(t, talk_ms=2_500, gap_ms=500, until=30_000)
    # つながなければ 2.5 / 3 で約 83。間をつなぐので、窓 (15 秒) のすべてを話していたことになる
    assert speech(t, 30_000) == 100
    assert t.score(30_000) == 100


def test_gap_of_1s_or_more_counts_as_silence() -> None:
    bridged = Tension(start_ms=0)
    bridged.step(SpeechStarted(), 0)
    bridged.step(SpeechEnded(), 5_000)
    bridged.step(SpeechStarted(), 5_999)  # 0.999 秒の間はつなぐ
    assert speech(bridged, 10_000) == pytest.approx(10_000 * 100 / 15_000)

    not_bridged = Tension(start_ms=0)
    not_bridged.step(SpeechStarted(), 0)
    not_bridged.step(SpeechEnded(), 5_000)
    not_bridged.step(SpeechStarted(), 6_000)  # ちょうど 1.0 秒の間は黙っていたと数える
    assert speech(not_bridged, 10_000) == 9_000 * 100 / 15_000


def test_score_while_talking_grows_by_the_bridged_gap() -> None:
    t = Tension(start_ms=0)
    t.step(SpeechStarted(), 0)
    t.step(SpeechEnded(), 2_000)
    t.step(SpeechStarted(), 2_500)
    # 話している途中: つながなければ 3.5 秒分、つなぐと間の 0.5 秒を足した 4 秒分
    assert speech(t, 4_000) == pytest.approx(4_000 * 100 / 15_000)
    assert speech(t, 4_000) - 3_500 * 100 / 15_000 == pytest.approx(500 * 100 / 15_000)


def test_gap_just_after_speech_ends_counts_until_1s_then_becomes_silence() -> None:
    t = Tension(start_ms=0)
    t.step(SpeechStarted(), 0)
    t.step(SpeechEnded(), 3_000)
    # 次の話し始めを待っている間 (1 秒未満) は、話していたとみなす
    assert speech(t, 3_500) == pytest.approx(3_500 * 100 / 15_000)
    assert speech(t, 3_999) == pytest.approx(3_999 * 100 / 15_000)
    # 1 秒たっても話し始めなければ、間はまとめて黙っていたと数える
    assert speech(t, 4_000) == 3_000 * 100 / 15_000
    assert speech(t, 6_000) == 3_000 * 100 / 15_000


def test_short_breaths_reach_high_that_was_out_of_reach() -> None:
    # 1 秒話して 0.7 秒の間 (話した割合は約 59 %)。つながなければ 70 に届かず High にならない
    t = Tension(start_ms=0)
    changes: list[tuple[int, TensionLevel]] = []
    now, talking_until = 0, 0
    t.step(SpeechStarted(), 0)
    while now < 20_000:
        now += TICK
        if now % 1_700 == 1_000:
            t.step(SpeechEnded(), now)
        elif now % 1_700 == 0:
            t.step(SpeechStarted(), now)
            talking_until = now
        outputs: list[Output] = t.step(Tick(), now)
        changes += [(now, o.level) for o in outputs if isinstance(o, TensionChanged)]
    assert talking_until > 0
    # 間をつなぐので、話し続けたとき (5.3 秒・10.5 秒) と同じ時刻に変わる
    assert changes == [(5_300, "normal"), (10_500, "high")]


def test_span_ending_before_window_still_bridges_into_window() -> None:
    # 窓の始まりの少し前に話し終わり、窓の中で話し始めた: 窓の中の間もつなぐ。
    # 確認用の読み出し (breakdown) と判定 (score) の値もそろう
    t = Tension(start_ms=0)
    t.step(SpeechStarted(), 0)
    t.step(SpeechEnded(), 10_000)
    t.step(SpeechStarted(), 10_600)
    now = 25_300  # 窓は 10.3 秒から。間 (10.0〜10.6 秒) のうち 0.3 秒が窓の中
    before = t.breakdown(now)
    assert t.score(now) == sum(before) == 100
    assert t.breakdown(now) == before


def test_mouth_and_silence_hunter_are_not_bridged() -> None:
    brain = Brain(start_ms=0, silence_seconds=5)
    log: list[tuple[int, Output]] = []

    def feed(now: int, event: SpeechStarted | SpeechEnded | Tick) -> None:
        log.extend((now, o) for o in brain.step(event, now))

    feed(0, SpeechStarted())
    feed(1_000, SpeechEnded())
    feed(1_500, SpeechStarted())  # 0.5 秒の間
    feed(2_000, SpeechEnded())
    for now in range(TICK, 10_000, TICK):
        feed(now, Tick())
    # 口パクは間でも閉じる
    assert [(t, o) for t, o in log if isinstance(o, Mouth)] == [
        (0, Mouth(speaking=True)),
        (1_000, Mouth(speaking=False)),
        (1_500, Mouth(speaking=True)),
        (2_000, Mouth(speaking=False)),
    ]
    # 沈黙は最後の話し終わり (2 秒) から数える (つないだ分ずれない)
    assert [(t, o) for t, o in log if isinstance(o, Say)] == [(7_100, Say("silence"))]
