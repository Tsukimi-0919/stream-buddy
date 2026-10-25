from stream_buddy.audio import BLOCK_SECONDS
from stream_buddy.detect import SpeechDetector, blocks_for

THRESHOLD = -40.0
LOUD = -20.0
QUIET = -60.0


def run(levels: list[float]) -> list[bool]:
    """音量の列を流し、通知された変化だけを返す。"""
    detector = SpeechDetector(THRESHOLD, BLOCK_SECONDS)
    return [c for c in (detector.update(level) for level in levels) if c is not None]


def test_end_is_300ms_of_blocks() -> None:
    assert SpeechDetector(THRESHOLD, BLOCK_SECONDS).end_blocks == 10
    assert blocks_for(0.3, 0.03) == 10
    assert blocks_for(0.3, 0.04) == 8


def test_silence_stays_silent() -> None:
    assert run([QUIET] * 100) == []


def test_single_noise_block_does_not_start() -> None:
    assert run([QUIET, LOUD, QUIET, QUIET, LOUD, QUIET]) == []


def test_two_loud_blocks_start_speaking() -> None:
    detector = SpeechDetector(THRESHOLD, BLOCK_SECONDS)
    assert detector.update(LOUD) is None
    assert detector.update(LOUD) is True
    assert detector.speaking


def test_threshold_itself_is_not_loud() -> None:
    # 「超える」ので、しきい値ちょうどは発話とみなさない
    assert run([THRESHOLD] * 10) == []


def test_short_breath_does_not_end_speaking() -> None:
    # 270 ms (9 ブロック) の息継ぎでは途切れない
    assert run([LOUD] * 5 + [QUIET] * 9 + [LOUD] * 5 + [QUIET] * 9) == [True]


def test_300ms_silence_ends_speaking() -> None:
    detector = SpeechDetector(THRESHOLD, BLOCK_SECONDS)
    for level in [LOUD] * 5 + [QUIET] * 9:
        detector.update(level)
    assert detector.speaking
    assert detector.update(QUIET) is False
    assert not detector.speaking


def test_threshold_counts_as_quiet_for_ending() -> None:
    assert run([LOUD] * 3 + [THRESHOLD] * 10) == [True, False]


def test_state_is_notified_only_on_change() -> None:
    levels = [LOUD] * 50 + [QUIET] * 50 + [LOUD] * 50 + [QUIET] * 50
    assert run(levels) == [True, False, True, False]


def test_counts_reset_after_change() -> None:
    # 話し終わりのあと、1 ブロックの大きな音だけでは話し始めにならない
    assert run([LOUD] * 3 + [QUIET] * 10 + [LOUD] + [QUIET] * 5) == [True, False]
