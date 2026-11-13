import pytest

from stream_buddy.state.event_fsm import EventMachine
from stream_buddy.state.events import Effect, EventKind, Hotkey, Keyword, Say, Tick


def started_at(now: int) -> EventMachine:
    m = EventMachine()
    m.step(Keyword("death"), now)
    assert m.state == "effecting"
    return m


def test_starts_ready() -> None:
    assert EventMachine().state == "ready"


def test_st21_keyword_starts_effect() -> None:
    m = EventMachine()
    assert m.step(Keyword("death"), 1_000) == [Effect("death"), Say("death")]
    assert (m.state, m.kind) == ("effecting", "death")


def test_st21_hotkey_starts_effect() -> None:
    m = EventMachine()
    assert m.step(Hotkey("clear"), 1_000) == [Effect("clear"), Say("clear")]
    assert (m.state, m.kind) == ("effecting", "clear")


def test_st22_effecting_to_cooldown_after_3s() -> None:
    m = started_at(1_000)
    assert m.step(Tick(), 3_999) == []
    assert m.state == "effecting"
    assert m.step(Tick(), 4_000) == []
    assert m.state == "cooldown"


def test_st23_cooldown_to_ready_5s_after_start() -> None:
    m = started_at(1_000)
    m.step(Tick(), 4_000)
    m.step(Tick(), 5_999)
    assert m.state == "cooldown"
    assert m.step(Tick(), 6_000) == []
    assert m.state == "ready"
    assert m.kind is None


def test_st23_waits_until_every_kind_has_waited_5s() -> None:
    m = started_at(1_000)  # death
    m.step(Keyword("clear"), 4_000)  # ST-26
    # death は 6 秒で 5 秒たつが、clear はまだなので Cooldown のまま
    m.step(Tick(), 7_000)
    m.step(Tick(), 8_999)
    assert m.state == "cooldown"
    m.step(Tick(), 9_000)
    assert m.state == "ready"


def test_st23_same_keyword_at_exactly_5s_is_accepted() -> None:
    # tick がなくても、時間による遷移を先に行ってから入力を扱う
    m = started_at(1_000)
    assert m.step(Keyword("death"), 6_000) == [Effect("death"), Say("death")]


def test_st24_hotkey_in_cooldown_starts_effect() -> None:
    m = started_at(1_000)
    assert m.step(Hotkey("clear"), 4_000) == [Effect("clear"), Say("clear")]
    assert (m.state, m.kind) == ("effecting", "clear")
    # 時間はホットキーの時刻から数え直す
    m.step(Tick(), 6_999)
    assert m.state == "effecting"
    m.step(Tick(), 7_000)
    assert m.state == "cooldown"
    m.step(Tick(), 8_999)
    assert m.state == "cooldown"
    m.step(Tick(), 9_000)
    assert m.state == "ready"


def test_st24_hotkey_of_same_kind_in_cooldown_starts_effect() -> None:
    # ホットキーは人がわざと押すものなので、同じ種類の待ち時間中でも受け付ける
    m = started_at(1_000)
    assert m.step(Hotkey("death"), 4_000) == [Effect("death"), Say("death")]


def test_same_keyword_within_5s_is_ignored() -> None:
    m = started_at(1_000)
    # 「死んだ死んだ！」のような連続は無視する
    for now in (4_000, 5_000, 5_999):
        assert m.step(Keyword("death"), now) == []
        assert m.state == "cooldown"
    assert m.step(Keyword("death"), 6_000) == [Effect("death"), Say("death")]


def test_same_keyword_boundary_4999_ignored_5000_accepted() -> None:
    m = started_at(0)
    assert m.step(Keyword("death"), 4_999) == []
    assert m.step(Keyword("death"), 5_000) == [Effect("death"), Say("death")]


def test_st26_other_keyword_in_cooldown_starts_effect() -> None:
    m = started_at(0)
    # 違う種類は、演出が終われば (3 秒後から) 受け付ける
    assert m.step(Keyword("clear"), 2_999) == []  # ST-25: 演出中
    assert m.state == "effecting"
    assert m.step(Keyword("clear"), 3_000) == [Effect("clear"), Say("clear")]
    assert (m.state, m.kind) == ("effecting", "clear")


def test_st26_clear_death_clear_uses_wait_per_kind() -> None:
    m = EventMachine()
    assert m.step(Keyword("clear"), 0) == [Effect("clear"), Say("clear")]  # ST-21
    assert m.step(Keyword("death"), 3_000) == [Effect("death"), Say("death")]  # ST-26
    # clear は前回 (0 秒) から 5 秒たっていても、death の演出中 (3〜6 秒) は無視する
    assert m.step(Keyword("clear"), 5_999) == []
    assert m.state == "effecting"
    # death の演出が終われば、clear は前回から 5 秒以上たっているので受け付ける
    assert m.step(Keyword("clear"), 6_000) == [Effect("clear"), Say("clear")]  # ST-26
    # death は前回 (3 秒) から 5 秒以上たち、clear の演出 (6〜9 秒) も終わったので受け付ける
    assert m.step(Keyword("death"), 9_000) == [Effect("death"), Say("death")]
    m2 = EventMachine()
    m2.step(Keyword("clear"), 0)
    m2.step(Keyword("death"), 3_000)
    m2.step(Keyword("clear"), 6_000)
    assert m2.step(Keyword("death"), 7_999) == []  # 演出中
    m2.step(Tick(), 9_000)
    assert m2.state == "cooldown"  # clear は 6 秒から 5 秒たっていない
    assert m2.step(Keyword("clear"), 10_999) == []  # 同じ種類の 5 秒以内
    assert m2.step(Keyword("clear"), 11_000) == [Effect("clear"), Say("clear")]


def test_st25_effecting_ignores_keywords_and_same_kind_hotkey() -> None:
    m = started_at(1_000)
    for now, event in [
        (1_000, Keyword("death")),  # 同じ種類のキーワード
        (2_000, Keyword("clear")),  # 違う種類のキーワード (聞き間違いで入れ替わらないように)
        (2_500, Hotkey("death")),  # 同じ種類のホットキー (出し直さない)
        (3_999, Hotkey("death")),
    ]:
        assert m.step(event, now) == []
        assert (m.state, m.kind) == ("effecting", "death")
    # 演出の長さは最初の開始から数えたまま
    m.step(Tick(), 4_000)
    assert m.state == "cooldown"


@pytest.mark.parametrize(("first", "second"), [("death", "clear"), ("clear", "death")])
def test_st27_other_kind_hotkey_switches_effect(first: EventKind, second: EventKind) -> None:
    m = EventMachine()
    m.step(Hotkey(first), 1_000)
    assert m.step(Hotkey(second), 2_000) == [Effect(second), Say(second)]
    assert (m.state, m.kind) == ("effecting", second)


def test_st27_effect_time_counts_from_switch() -> None:
    m = started_at(1_000)  # death
    assert m.step(Hotkey("clear"), 2_500) == [Effect("clear"), Say("clear")]  # ST-27
    # 3 秒は clear の開始 (2.5 秒) から数える
    m.step(Tick(), 5_499)
    assert (m.state, m.kind) == ("effecting", "clear")
    m.step(Tick(), 5_500)
    assert m.state == "cooldown"
    # clear の前回の演出開始も 2.5 秒になる。death は 6 秒で 5 秒たつが、clear は 7.5 秒まで待つ
    assert m.step(Keyword("clear"), 7_499) == []
    m.step(Tick(), 7_499)
    assert m.state == "cooldown"
    m.step(Tick(), 7_500)
    assert m.state == "ready"


def test_st27_switch_back_and_forth() -> None:
    m = started_at(0)  # death
    assert m.step(Hotkey("clear"), 1_000) == [Effect("clear"), Say("clear")]
    assert m.step(Hotkey("clear"), 1_500) == []  # 同じ種類は無視 (ST-25)
    assert m.step(Hotkey("death"), 2_000) == [Effect("death"), Say("death")]  # ST-27
    assert m.step(Keyword("clear"), 2_500) == []  # キーワードは無視 (ST-25)
    assert (m.state, m.kind) == ("effecting", "death")
