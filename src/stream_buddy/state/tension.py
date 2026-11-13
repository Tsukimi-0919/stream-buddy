"""テンションの状態機械 (ST-01〜ST-05、FR-04)。"""

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

    def __init__(
        self,
        start_ms: int,
        *,
        window_ms: int = c.TENSION_WINDOW_MS,
        hold_ms: int = c.TENSION_HOLD_MS,
    ) -> None:
        """window_ms は話していた割合を数える窓、hold_ms は変わったあと変えない時間。

        どちらも設定の [tension] から渡す (既定値は constants の値)。
        """
        if window_ms <= 0 or hold_ms < 0:
            raise ValueError("window_ms は正、hold_ms は 0 以上にしてください")
        self._window_ms = window_ms
        self._hold_ms = hold_ms
        self.level: TensionLevel = "calm"
        # 起動直後も hold_ms は変えない
        self._last_change_ms = start_ms
        # 話していた区間 (開始, 終了)。終了が None なら話している最中
        self._spans: list[tuple[int, int | None]] = []
        self._bonuses: list[_Bonus] = []
        # ST-05 の 15 秒を数え始めた時刻 (High に入った時刻か、前回の Say(cheer) の時刻)
        self._cheer_from_ms = start_ms

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
        speech, bonus = self.breakdown(now_ms)
        return min(c.TENSION_MAX, max(c.TENSION_MIN, speech + bonus))

    def breakdown(self, now_ms: int) -> tuple[float, float]:
        """盛り上がり度の内訳 (話していた割合 * 100、補正の合計)。0〜100 に収める前の値。

        状態は変えない (窓の外のものは 0 として数えるだけで、捨てない)。
        """
        window_start = now_ms - self._window_ms
        spoken = 0
        for start, end in self._spoken_intervals(now_ms):
            spoken += max(0, end - max(start, window_start))
        bonus = sum(b.value_at(now_ms) for b in self._bonuses)
        # 割り算は 1 回だけにし、しきい値ちょうどで誤差が出ないようにする
        return spoken * 100 / self._window_ms, bonus

    @property
    def last_change_ms(self) -> int:
        """前回テンションが変わった時刻 (まだ変わっていなければ起動時刻)。"""
        return self._last_change_ms

    @property
    def _speaking(self) -> bool:
        return bool(self._spans) and self._spans[-1][1] is None

    def _spoken_intervals(self, now_ms: int) -> list[tuple[int, int]]:
        """話していたとみなす区間 (開始, 終了)。話している最中は「今」までとする。

        話し終わりから次の話し始めまでが TENSION_GAP_BRIDGE_MS 未満なら、その間も話していた
        とみなしてつなぐ (息継ぎや文の切れ目を黙っていたと数えないため)。
        話し終わって間もなく、次の話し始めを待っている間も、話していたとみなす。
        その時間をすぎても話し始めなければ、間はまとめて黙っていたと数える。
        状態は変えない (時刻と、話していた区間だけで決まる)。
        """
        merged: list[tuple[int, int]] = []
        for start, end in self._spans:
            end_ms = now_ms if end is None else end
            if merged and start - merged[-1][1] < c.TENSION_GAP_BRIDGE_MS:
                merged[-1] = (merged[-1][0], end_ms)
            else:
                merged.append((start, end_ms))
        if merged and not self._speaking and now_ms - merged[-1][1] < c.TENSION_GAP_BRIDGE_MS:
            merged[-1] = (merged[-1][0], now_ms)
        return merged

    def _forget(self, now_ms: int) -> None:
        # 窓の始まりより前に終わった区間でも、窓の中の間をつなぐのに使うものは残す
        keep_after = now_ms - self._window_ms - c.TENSION_GAP_BRIDGE_MS
        self._spans = [s for s in self._spans if s[1] is None or s[1] > keep_after]
        self._bonuses = [b for b in self._bonuses if now_ms - b.start_ms < c.BONUS_DECAY_MS]

    def _judge(self, now_ms: int) -> list[Output]:
        outputs = self._change_level(now_ms)
        if not outputs and self.level == "high":
            outputs = self._cheer(now_ms)
        return outputs

    def _change_level(self, now_ms: int) -> list[Output]:
        if now_ms - self._last_change_ms < self._hold_ms:
            return []
        value = self.score(now_ms)
        match self.level:
            case "calm" if value >= c.CALM_TO_NORMAL:
                return self._change("normal", now_ms)  # ST-01
            case "normal" if value < c.NORMAL_TO_CALM:
                return self._change("calm", now_ms)  # ST-02
            case "normal" if value >= c.NORMAL_TO_HIGH:
                self._cheer_from_ms = now_ms  # ST-05 は High に入ったときから数える
                return [*self._change("high", now_ms), TensionPeak(), Say("high")]  # ST-03
            case "high" if value < c.HIGH_TO_NORMAL:
                return self._change("normal", now_ms)  # ST-04
        return []

    def _cheer(self, now_ms: int) -> list[Output]:
        # ST-05。出口で捨てられても言ったものとして数え直す (後で出し直さない)
        if now_ms - self._cheer_from_ms < c.CHEER_INTERVAL_MS:
            return []
        self._cheer_from_ms = now_ms
        return [Say("cheer")]

    def _change(self, level: TensionLevel, now_ms: int) -> list[Output]:
        self.level = level
        self._last_change_ms = now_ms
        return [TensionChanged(level)]
