"""イベントの状態機械 (ST-21〜ST-25、FR-07〜FR-09)。"""

from typing import Literal

from stream_buddy.state import constants as c
from stream_buddy.state.events import Effect, EventKind, Hotkey, Keyword, Output, Say, Tick

type EventInput = Keyword | Hotkey | Tick
type EventState = Literal["ready", "effecting", "cooldown"]


class EventMachine:
    """死亡・クリアの演出を出し、連続で出さないための待ち時間を持つ。"""

    def __init__(self) -> None:
        self.state: EventState = "ready"
        self.kind: EventKind | None = None
        self._started_ms = 0

    def step(self, event: EventInput, now_ms: int) -> list[Output]:
        # 時間による遷移を先に行う (境界の時刻に来た入力も、遷移後の状態で扱う)
        self._advance(now_ms)
        match event:
            case Keyword(kind) | Hotkey(kind) if self.state == "ready":
                return self._start(kind, now_ms)  # ST-21
            case Hotkey(kind) if self.state == "cooldown":
                return self._start(kind, now_ms)  # ST-24
        # Cooldown 中のキーワードと、Effecting 中の入力 (ST-25) は無視する
        return []

    def _advance(self, now_ms: int) -> None:
        elapsed = now_ms - self._started_ms
        if self.state == "effecting" and elapsed >= c.EFFECT_MS:
            self.state = "cooldown"  # ST-22
        if self.state == "cooldown" and elapsed >= c.EVENT_COOLDOWN_MS:
            self.state = "ready"  # ST-23
            self.kind = None

    def _start(self, kind: EventKind, now_ms: int) -> list[Output]:
        self.state = "effecting"
        self.kind = kind
        self._started_ms = now_ms
        return [Effect(kind), Say(kind)]
