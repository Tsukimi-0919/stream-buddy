"""テンションの窓と待ちを設定で変えたときの動き (T-23)。

既定の窓 15 秒・待ち 3 秒で、100 ms ごとに Tick を入れて確かめる。
窓 30 秒・待ち 5 秒 (v1.1.0 まで) の動きは test_tension.py と test_brain.py で確かめている。
"""

import pytest

from stream_buddy.state import constants as c
from stream_buddy.state.events import (
    Effect,
    Output,
    SpeechEnded,
    SpeechStarted,
    TensionChanged,
    TensionLevel,
    Tick,
)
from stream_buddy.state.tension import Tension

TICK = c.TICK_MS


class Run:
    """Tension に 100 ms ごとに Tick を入れ、テンションが変わった時刻を集める。"""

    def __init__(self, **kwargs: int) -> None:
        self.tension = Tension(start_ms=0, **kwargs)
        self.now = 0
        self.changes: list[tuple[int, TensionLevel]] = []

    def until(self, end: int) -> None:
        while self.now + TICK <= end:
            self.now += TICK
            self._collect(self.tension.step(Tick(), self.now))

    def at(self, when: int, event: SpeechStarted | SpeechEnded | Effect) -> None:
        self.until(when)
        self._collect(self.tension.step(event, when))

    def _collect(self, outputs: list[Output]) -> None:
        self.changes += [(self.now, o.level) for o in outputs if isinstance(o, TensionChanged)]


def test_defaults_are_15s_window_and_3s_hold() -> None:
    assert (c.TENSION_WINDOW_MS, c.TENSION_HOLD_MS) == (15_000, 3_000)


def test_talking_from_silence_reaches_normal_at_5_3s_and_high_at_10_5s() -> None:
    run = Run()
    run.at(0, SpeechStarted())
    run.until(15_000)
    # 35 % は 5.25 秒、70 % は 10.5 秒。Tick は 100 ms ごとなので 5.3 秒と 10.5 秒
    assert run.changes == [(5_300, "normal"), (10_500, "high")]


def test_silence_after_talk_returns_to_normal_in_7_5s_then_calm_in_12s() -> None:
    run = Run()
    run.at(0, SpeechStarted())
    run.at(20_000, SpeechEnded())
    run.until(40_000)
    # 黙ってから、窓から話した時間が抜けていく。50 % 未満は 7.5 秒より後、20 % 未満は 12 秒より後
    assert run.changes == [
        (5_300, "normal"),
        (10_500, "high"),
        (27_600, "normal"),
        (32_100, "calm"),
    ]


def test_no_change_within_3s_after_a_change_even_above_threshold() -> None:
    run = Run()
    run.at(0, SpeechStarted())
    run.until(5_300)
    assert run.changes == [(5_300, "normal")]
    # 6 秒にクリアの加点 (+30) で 70 をこえるが、Normal になってから 3 秒 (8.3 秒) までは変えない
    run.at(6_000, Effect("clear"))
    assert run.tension.score(6_000) >= c.NORMAL_TO_HIGH
    run.until(8_200)
    assert run.changes == [(5_300, "normal")]
    run.until(8_300)
    assert run.changes == [(5_300, "normal"), (8_300, "high")]


def test_starts_without_change_for_hold_after_start() -> None:
    # 起動直後も待ちの時間は変えない (窓 5 秒なら 1.75 秒で 35 % をこえるが、待ち 3 秒まで変えない)
    run = Run(window_ms=5_000, hold_ms=3_000)
    run.at(0, SpeechStarted())
    run.until(3_000)
    assert run.changes == [(3_000, "normal")]


@pytest.mark.parametrize("window_ms", [5_000, 15_000, 30_000])
def test_score_stays_within_0_to_100_for_any_window(window_ms: int) -> None:
    run = Run(window_ms=window_ms, hold_ms=1_000)
    run.at(0, SpeechStarted())
    run.at(1_000, Effect("clear"))
    run.until(2 * window_ms)
    speech, _ = run.tension.breakdown(run.now)
    assert speech == 100  # 窓の全部を話していれば 100 (それ以上にはならない)
    assert run.tension.score(run.now) == 100
    run.at(run.now, SpeechEnded())
    run.at(run.now + 500, Effect("death"))
    run.until(run.now + 3 * window_ms)
    assert run.tension.breakdown(run.now)[0] == 0
    assert run.tension.score(run.now) == 0


def test_window_and_hold_of_v1_0_behave_as_before() -> None:
    # 窓 30 秒・待ち 5 秒を渡すと、v1.1.0 までと同じ時刻に変わる
    run = Run(window_ms=30_000, hold_ms=5_000)
    run.at(0, SpeechStarted())
    run.until(30_000)
    assert run.changes == [(10_500, "normal"), (21_000, "high")]


@pytest.mark.parametrize(("window_ms", "hold_ms"), [(0, 3_000), (-1, 3_000), (15_000, -1)])
def test_invalid_window_or_hold_is_rejected(window_ms: int, hold_ms: int) -> None:
    with pytest.raises(ValueError, match="window_ms"):
        Tension(start_ms=0, window_ms=window_ms, hold_ms=hold_ms)
