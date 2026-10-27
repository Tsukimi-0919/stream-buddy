from stream_buddy.state.arbiter import Arbiter
from stream_buddy.state.events import Effect, Mouth, Say, TensionChanged, TensionPeak


def test_first_say_is_shown() -> None:
    assert Arbiter().filter([Say("silence")], 0) == [Say("silence")]


def test_silence_within_3s_is_dropped() -> None:
    a = Arbiter()
    a.filter([Say("high")], 10_000)
    assert a.filter([Say("silence")], 12_999) == []
    # 捨てたものは出し直さない。間隔は最後に「出した」吹き出しから数える
    assert a.filter([Say("silence")], 13_000) == [Say("silence")]


def test_high_within_3s_is_dropped() -> None:
    a = Arbiter()
    a.filter([Say("silence")], 10_000)
    assert a.filter([Say("high")], 12_999) == []
    assert a.filter([Say("high")], 13_000) == [Say("high")]


def test_cheer_within_3s_is_dropped() -> None:
    a = Arbiter()
    a.filter([Say("high")], 10_000)
    assert a.filter([Say("cheer")], 12_999) == []
    assert a.filter([Say("cheer")], 13_000) == [Say("cheer")]


def test_clear_and_death_ignore_interval() -> None:
    a = Arbiter()
    a.filter([Say("silence")], 10_000)
    assert a.filter([Say("clear")], 10_000) == [Say("clear")]
    assert a.filter([Say("death")], 10_001) == [Say("death")]
    # death / clear も「前に出した吹き出し」になる
    assert a.filter([Say("silence")], 13_000) == []


def test_simultaneous_says_keep_highest_priority() -> None:
    a = Arbiter()
    assert a.filter([Say("silence"), Say("high")], 0) == [Say("high")]
    assert a.filter([Say("silence"), Say("clear")], 3_000) == [Say("clear")]
    assert a.filter([Say("silence"), Say("cheer")], 6_000) == [Say("cheer")]
    assert a.filter([Say("cheer"), Say("death")], 6_001) == [Say("death")]


def test_other_outputs_pass_through_in_order() -> None:
    a = Arbiter()
    a.filter([Say("clear")], 0)
    outputs = [
        Mouth(speaking=True),
        TensionChanged("high"),
        TensionPeak(),
        Say("high"),
        Effect("clear"),
    ]
    assert a.filter(outputs, 1_000) == [
        Mouth(speaking=True),
        TensionChanged("high"),
        TensionPeak(),
        Effect("clear"),
    ]
