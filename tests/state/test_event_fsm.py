from stream_buddy.state.event_fsm import EventMachine
from stream_buddy.state.events import Effect, Hotkey, Keyword, Say, Tick


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


def test_st23_cooldown_to_ready_10s_after_start() -> None:
    m = started_at(1_000)
    m.step(Tick(), 4_000)
    m.step(Tick(), 10_999)
    assert m.state == "cooldown"
    assert m.step(Tick(), 11_000) == []
    assert m.state == "ready"
    assert m.kind is None


def test_st23_keyword_at_exactly_10s_is_accepted() -> None:
    # tick がなくても、時間による遷移を先に行ってから入力を扱う
    m = started_at(1_000)
    assert m.step(Keyword("clear"), 11_000) == [Effect("clear"), Say("clear")]


def test_st24_hotkey_in_cooldown_starts_effect() -> None:
    m = started_at(1_000)
    assert m.step(Hotkey("clear"), 4_000) == [Effect("clear"), Say("clear")]
    assert (m.state, m.kind) == ("effecting", "clear")
    # 時間はホットキーの時刻から数え直す
    m.step(Tick(), 6_999)
    assert m.state == "effecting"
    m.step(Tick(), 7_000)
    assert m.state == "cooldown"
    m.step(Tick(), 13_999)
    assert m.state == "cooldown"
    m.step(Tick(), 14_000)
    assert m.state == "ready"


def test_st24_keyword_in_cooldown_is_ignored() -> None:
    m = started_at(1_000)
    # 「死んだ死んだ！」のような連続は無視する
    for now in (4_000, 6_000, 10_999):
        assert m.step(Keyword("death"), now) == []
        assert m.state == "cooldown"


def test_st25_effecting_ignores_everything() -> None:
    m = started_at(1_000)
    for now, event in [
        (1_000, Keyword("death")),
        (2_000, Keyword("clear")),
        (2_500, Hotkey("clear")),
        (3_999, Hotkey("death")),
    ]:
        assert m.step(event, now) == []
        assert (m.state, m.kind) == ("effecting", "death")
