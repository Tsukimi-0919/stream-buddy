from stream_buddy.state.events import Output, Say, SpeechEnded, SpeechStarted, Tick
from stream_buddy.state.silence import SilenceHunter

TICK = 100


def ticks(h: SilenceHunter, start: int, end: int, *, paused: bool = False) -> list[int]:
    """start より後から end まで 100 ms ごとに tick を入れ、Say(silence) が出た時刻を返す。"""
    said = []
    for now in range(start + TICK, end + 1, TICK):
        out: list[Output] = h.step(Tick(), now, paused=paused)
        if out:
            assert out == [Say("silence")]
            said.append(now)
    return said


def waiting_from(ended_ms: int) -> SilenceHunter:
    h = SilenceHunter(start_ms=0, silence_seconds=20)
    h.step(SpeechStarted(), 0)
    h.step(SpeechEnded(), ended_ms)
    return h


def test_startup_is_listening_and_does_not_count() -> None:
    h = SilenceHunter(start_ms=0, silence_seconds=20)
    assert h.state == "listening"
    # 最初に話し終わるまでは、何分黙っていても話しかけない
    assert ticks(h, 0, 300_000) == []


def test_st11_listening_to_waiting() -> None:
    h = SilenceHunter(start_ms=0, silence_seconds=20)
    assert h.step(SpeechEnded(), 1_000) == []
    assert h.state == "waiting"
    assert (h.calls, h.wait_ms, h.silent_ms) == (0, 20_000, 0)


def test_st12_waiting_to_listening() -> None:
    h = waiting_from(0)
    ticks(h, 0, 10_000)
    assert h.step(SpeechStarted(), 10_000) == []
    assert h.state == "listening"
    # 話している間は数えない
    assert ticks(h, 10_000, 100_000) == []


def test_st13_says_after_wait_is_exceeded() -> None:
    h = waiting_from(0)
    # 20 秒ちょうどは「超えた」ではない
    assert ticks(h, 0, 20_000) == []
    assert h.step(Tick(), 20_100) == [Say("silence")]
    # 回数 +1、待ち時間 2 倍、数え直し
    assert (h.state, h.calls, h.wait_ms, h.silent_ms) == ("waiting", 1, 40_000, 0)


def test_st13_st14_20_40_80_then_gives_up() -> None:
    h = waiting_from(0)
    # 20 秒 → 40 秒 → 80 秒 (それぞれ話しかけた時点から数え直す)。そのあとは黙る
    assert ticks(h, 0, 1_000_000) == [20_100, 60_200, 140_300]
    assert h.state == "gave_up"
    assert h.calls == 3


def test_st14_gives_up_right_after_third_call() -> None:
    h = waiting_from(0)
    ticks(h, 0, 140_200)
    assert h.state == "waiting"
    assert h.step(Tick(), 140_300) == [Say("silence")]
    assert h.state == "gave_up"


def test_st15_gave_up_to_listening_and_starts_over() -> None:
    h = waiting_from(0)
    ticks(h, 0, 200_000)
    assert h.state == "gave_up"
    assert h.step(SpeechStarted(), 200_000) == []
    assert h.state == "listening"
    # 話し終わったら最初 (20 秒、0 回) から
    h.step(SpeechEnded(), 201_000)
    assert (h.state, h.calls, h.wait_ms) == ("waiting", 0, 20_000)
    assert ticks(h, 201_000, 222_000) == [221_100]


def test_st12_speaking_resets_after_a_call() -> None:
    h = waiting_from(0)
    ticks(h, 0, 30_000)
    assert h.calls == 1
    h.step(SpeechStarted(), 30_000)
    h.step(SpeechEnded(), 31_000)
    assert (h.calls, h.wait_ms) == (0, 20_000)


def test_paused_time_is_not_counted() -> None:
    h = waiting_from(0)
    assert ticks(h, 0, 10_000) == []
    # 演出中の 5 秒は数えない
    assert ticks(h, 10_000, 15_000, paused=True) == []
    assert h.silent_ms == 10_000
    assert ticks(h, 15_000, 25_000) == []
    assert h.step(Tick(), 25_100) == [Say("silence")]
