from stream_buddy.state.events import (
    Effect,
    Say,
    SpeechEnded,
    SpeechStarted,
    TensionChanged,
    TensionPeak,
    Tick,
)
from stream_buddy.state.tension import Tension


def to_normal() -> Tension:
    """0〜12 秒に話し、10.5 秒 (盛り上がり度 35) で Normal にしたもの。"""
    t = Tension(start_ms=0)
    t.step(SpeechStarted(), 0)
    assert t.step(Tick(), 10_500) == [TensionChanged("normal")]
    t.step(SpeechEnded(), 12_000)
    return t


def to_high() -> Tension:
    """0〜21 秒に話し、21 秒 (盛り上がり度 70) で High にしたもの。"""
    t = Tension(start_ms=0)
    t.step(SpeechStarted(), 0)
    t.step(Tick(), 10_500)
    t.step(SpeechEnded(), 21_000)
    assert t.step(Tick(), 21_000)[0] == TensionChanged("high")
    return t


def test_starts_calm() -> None:
    assert Tension(start_ms=0).level == "calm"


def test_st01_calm_to_normal() -> None:
    t = Tension(start_ms=0)
    t.step(SpeechStarted(), 0)
    t.step(SpeechEnded(), 10_500)
    # 30 秒のうち 10.5 秒 = 35 (しきい値ちょうど) で変わる
    assert t.score(10_500) == 35
    assert t.step(Tick(), 10_500) == [TensionChanged("normal")]
    assert t.level == "normal"


def test_st01_just_below_threshold_stays_calm() -> None:
    t = Tension(start_ms=0)
    t.step(SpeechStarted(), 0)
    t.step(SpeechEnded(), 10_499)
    assert t.step(Tick(), 10_500) == []
    assert t.level == "calm"


def test_st01_speaking_counts_up_to_now() -> None:
    # 話している最中は「今」までを数える
    t = Tension(start_ms=0)
    t.step(SpeechStarted(), 0)
    assert t.score(10_500) == 35
    assert t.step(Tick(), 10_500) == [TensionChanged("normal")]


def test_st01_not_within_5s_of_startup() -> None:
    # 起動の 30 秒前から話していた扱い。盛り上がり度は 100 でも、起動直後の 5 秒は変えない
    t = Tension(start_ms=30_000)
    t.step(SpeechStarted(), 0)
    assert t.step(Tick(), 34_999) == []
    assert t.step(Tick(), 35_000) == [TensionChanged("normal")]


def test_st01_calm_does_not_jump_to_high() -> None:
    t = Tension(start_ms=0)
    t.step(SpeechStarted(), 0)
    # 盛り上がり度 70 以上でも、Calm からはまず Normal
    assert t.score(21_000) == 70
    assert t.step(Tick(), 21_000) == [TensionChanged("normal")]
    # 変わってから 5 秒は変えない
    assert t.step(Tick(), 25_999) == []
    assert t.step(Tick(), 26_000) == [TensionChanged("high"), TensionPeak(), Say("high")]


def test_st02_normal_to_calm() -> None:
    t = Tension(start_ms=0)
    t.step(SpeechStarted(), 0)
    t.step(SpeechEnded(), 10_500)
    t.step(Tick(), 10_500)
    # 窓から話した時間が抜けていく。34.5 秒で 6 秒 = 20 (しきい値ちょうど) は変わらない
    assert t.score(34_500) == 20
    assert t.step(Tick(), 34_500) == []
    assert t.step(Tick(), 34_600) == [TensionChanged("calm")]
    assert t.level == "calm"


def test_st03_normal_to_high() -> None:
    t = Tension(start_ms=0)
    t.step(SpeechStarted(), 0)
    t.step(Tick(), 10_500)
    assert t.step(Tick(), 20_999) == []
    t.step(SpeechEnded(), 21_000)
    # 70 ちょうどで High。TensionPeak と Say(high) も出す
    assert t.step(Tick(), 21_000) == [TensionChanged("high"), TensionPeak(), Say("high")]
    assert t.level == "high"


def test_st03_not_within_5s_of_change() -> None:
    t = to_normal()
    # 変わった直後に盛り上がっても、5 秒たつまでは変えない
    t.step(Effect("clear"), 10_600)
    t.step(Effect("clear"), 10_600)
    assert t.score(15_499) >= 70
    assert t.step(Tick(), 15_499) == []
    assert t.step(Tick(), 15_500)[0] == TensionChanged("high")


def test_st04_high_to_normal() -> None:
    t = to_high()
    # 36 秒で 15 秒 = 50 (しきい値ちょうど) は変わらない
    assert t.score(36_000) == 50
    assert t.step(Tick(), 36_000) == []
    assert t.step(Tick(), 36_100) == [TensionChanged("normal")]


def test_st04_high_does_not_jump_to_calm() -> None:
    t = to_high()
    # 盛り上がり度 0 でも、High からはまず Normal
    assert t.score(60_000) == 0
    assert t.step(Tick(), 60_000) == [TensionChanged("normal")]
    assert t.step(Tick(), 64_999) == []
    assert t.step(Tick(), 65_000) == [TensionChanged("calm")]


def test_st03_clear_bonus_raises_normal_to_high() -> None:
    t = to_normal()
    assert t.step(Tick(), 20_000) == []  # 40 のままなら Normal
    t.step(Effect("clear"), 20_000)
    assert t.score(20_000) == 70
    assert t.step(Tick(), 20_000)[0] == TensionChanged("high")


def test_st02_death_penalty_lowers_normal_to_calm() -> None:
    t = to_normal()
    t.step(Effect("death"), 20_000)
    assert t.score(20_000) == 10
    assert t.step(Tick(), 20_000) == [TensionChanged("calm")]


def test_bonus_decays_linearly_in_10s() -> None:
    t = Tension(start_ms=0)
    t.step(Effect("clear"), 0)
    assert t.score(0) == 30
    assert t.score(5_000) == 15
    assert t.score(9_999) > 0
    assert t.score(10_000) == 0


def test_score_is_clamped_to_0_and_100() -> None:
    t = Tension(start_ms=0)
    t.step(Effect("death"), 0)
    assert t.score(0) == 0
    t.step(SpeechStarted(), 0)
    t.step(Effect("clear"), 30_000)
    assert t.score(30_000) == 100


def test_only_tick_judges() -> None:
    t = Tension(start_ms=0)
    t.step(SpeechStarted(), 0)
    assert t.step(SpeechEnded(), 20_000) == []
    assert t.step(Effect("clear"), 20_000) == []
    assert t.level == "calm"
