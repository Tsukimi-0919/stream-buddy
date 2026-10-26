"""出口 (FR-06): 吹き出し (Say) の出しすぎを防ぐ。セリフの選択は T-09 で行う。"""

from stream_buddy.state import constants as c
from stream_buddy.state.events import Output, Say, Situation

# 小さいほど優先度が高い
PRIORITY: dict[Situation, int] = {"death": 1, "clear": 1, "high": 2, "silence": 3}
# 前の吹き出しからの間隔に関係なく出すもの
ALWAYS: frozenset[Situation] = frozenset({"death", "clear"})


class Arbiter:
    def __init__(self) -> None:
        self._last_say_ms: int | None = None

    def filter(self, outputs: list[Output], now_ms: int) -> list[Output]:
        """同じ時刻に来た出力を整理する。Say 以外は間引かない。

        Say は優先度の最も高い 1 つだけを残し、出せないものは捨てる (後で出し直さない)。
        """
        says = [o for o in outputs if isinstance(o, Say)]
        if not says:
            return outputs
        best = min(says, key=lambda s: PRIORITY[s.situation])
        keep = best.situation in ALWAYS or (
            self._last_say_ms is None or now_ms - self._last_say_ms >= c.SAY_MIN_INTERVAL_MS
        )
        if keep:
            self._last_say_ms = now_ms
        return [o for o in outputs if not isinstance(o, Say) or (keep and o is best)]
