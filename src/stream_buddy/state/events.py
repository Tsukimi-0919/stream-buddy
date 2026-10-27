"""状態機械の入力と出力。"""

from dataclasses import dataclass
from typing import Literal

type EventKind = Literal["death", "clear"]
type TensionLevel = Literal["calm", "normal", "high"]
type Situation = Literal["death", "clear", "high", "cheer", "silence"]

# 入力


@dataclass(frozen=True)
class SpeechStarted:
    pass


@dataclass(frozen=True)
class SpeechEnded:
    pass


@dataclass(frozen=True)
class Keyword:
    kind: EventKind


@dataclass(frozen=True)
class Hotkey:
    kind: EventKind


@dataclass(frozen=True)
class Tick:
    pass


type Input = SpeechStarted | SpeechEnded | Keyword | Hotkey | Tick

# 出力


@dataclass(frozen=True)
class Mouth:
    speaking: bool


@dataclass(frozen=True)
class TensionChanged:
    level: TensionLevel


@dataclass(frozen=True)
class Say:
    situation: Situation


@dataclass(frozen=True)
class Effect:
    kind: EventKind


@dataclass(frozen=True)
class TensionPeak:
    pass


type Output = Mouth | TensionChanged | Say | Effect | TensionPeak
