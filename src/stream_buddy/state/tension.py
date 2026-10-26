"""テンションの状態機械 (ST-01〜ST-04、FR-04)。"""

from dataclasses import dataclass

from stream_buddy.state import constants as c
from stream_buddy.state.events import (
    Effect,
    Output,
    Say,
    SpeechEnded,
    SpeechStarted,
    TensionChanged,
    TensionLevel,
    TensionPeak,
    Tick,
)

# テンションが受け取る入力。Effect は Brain がイベントの状態機械の出力から渡す
type TensionInput = SpeechStarted | SpeechEnded | Tick | Effect


@dataclass(frozen=True)
class _Bonus:
    start_ms: int
    amount: int

    def value_at(self, now_ms: int) -> float:
        """直線的に 0 に戻る。開始の瞬間が amount、BONUS_DECAY_MS 後に 0。"""
        elapsed = now_ms - self.start_ms
        if elapsed >= c.BONUS_DECAY_MS:
            return 0.0
        return self.amount * (c.BONUS_DECAY_MS - elapsed) / c.BONUS_DECAY_MS


class Tension:
    """話している割合とイベントの補正から、Calm / Normal / High を決める。"""

    def __init__(self, start_ms: int) -> None:
        self.level: TensionLevel = "calm"
        # 起動直後も TENSION_HOLD_MS は変えない
        self._last_change_ms = start_ms
        # 話していた区間 (開始, 終了)。終了が None なら話している最中
        self._spans: list[tuple[int, int | None]] = []
        self._bonuses: list[_Bonus] = []

    def step(self, event: TensionInput, now_ms: int) -> list[Output]:
        match event:
            case SpeechStarted():
                if not self._speaking:
                    self._spans.append((now_ms, None))
            case SpeechEnded():
                if self._speaking:
                    start, _ = self._spans[-1]
                    self._spans[-1] = (start, now_ms)
            case Effect(kind):
                amount = c.CLEAR_BONUS if kind == "clear" else c.DEATH_BONUS
                self._bonuses.append(_Bonus(now_ms, amount))
            case Tick():
                return self._judge(now_ms)
        return []

    def score(self, now_ms: int) -> float:
        """盛り上がり度 (0〜100)。直近の窓で話していた割合 * 100 + 補正。"""
        self._forget(now_ms)
        window_start = now_ms - c.TENSION_WINDOW_MS
        spoken = 0
        for start, end in self._spans:
            # 話している最中は「今」までを数える
            end_ms = now_ms if end is None else end
            spoken += max(0, end_ms - max(start, window_start))
        bonus = sum(b.value_at(now_ms) for b in self._bonuses)
        # 割り算は最後に 1 回だけにし、しきい値ちょうどで誤差が出ないようにする
        value = spoken * 100 / c.TENSION_WINDOW_MS + bonus
        return min(c.TENSION_MAX, max(c.TENSION_MIN, value))

    @property
    def _speaking(self) -> bool:
        return bool(self._spans) and self._spans[-1][1] is None

    def _forget(self, now_ms: int) -> None:
        window_start = now_ms - c.TENSION_WINDOW_MS
        self._spans = [s for s in self._spans if s[1] is None or s[1] > window_start]
        self._bonuses = [b for b in self._bonuses if now_ms - b.start_ms < c.BONUS_DECAY_MS]

    def _judge(self, now_ms: int) -> list[Output]:
        if now_ms - self._last_change_ms < c.TENSION_HOLD_MS:
            return []
        value = self.score(now_ms)
        match self.level:
            case "calm" if value >= c.CALM_TO_NORMAL:
                return self._change("normal", now_ms)  # ST-01
            case "normal" if value < c.NORMAL_TO_CALM:
                return self._change("calm", now_ms)  # ST-02
            case "normal" if value >= c.NORMAL_TO_HIGH:
                return [*self._change("high", now_ms), TensionPeak(), Say("high")]  # ST-03
            case "high" if value < c.HIGH_TO_NORMAL:
                return self._change("normal", now_ms)  # ST-04
        return []

    def _change(self, level: TensionLevel, now_ms: int) -> list[Output]:
        self.level = level
        self._last_change_ms = now_ms
        return [TensionChanged(level)]
