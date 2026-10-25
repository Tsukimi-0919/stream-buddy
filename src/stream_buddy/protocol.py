"""WebSocket のメッセージ (docs/ws-protocol.md) の pydantic モデル。"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

from stream_buddy.config import Background

PROTOCOL_VERSION: Literal[0] = 0
MAX_MESSAGE_BYTES = 4096
MAX_SAY_TEXT_LENGTH = 80


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


# ページ → サーバー


class HelloPayload(_Model):
    page_version: Annotated[str, StringConstraints(min_length=1, max_length=32)]


class Hello(_Model):
    v: Literal[0]
    type: Literal["hello"]
    payload: HelloPayload


# サーバー → ページ


class SpeechPayload(_Model):
    speaking: bool


class Speech(_Model):
    v: Literal[0] = PROTOCOL_VERSION
    type: Literal["speech"] = "speech"
    payload: SpeechPayload


class TensionPayload(_Model):
    level: Literal["calm", "normal", "high"]


class Tension(_Model):
    v: Literal[0] = PROTOCOL_VERSION
    type: Literal["tension"] = "tension"
    payload: TensionPayload


class SayPayload(_Model):
    line_id: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    text: Annotated[str, StringConstraints(min_length=1, max_length=MAX_SAY_TEXT_LENGTH)]


class Say(_Model):
    v: Literal[0] = PROTOCOL_VERSION
    type: Literal["say"] = "say"
    payload: SayPayload


class EffectPayload(_Model):
    kind: Literal["death", "clear"]


class Effect(_Model):
    v: Literal[0] = PROTOCOL_VERSION
    type: Literal["effect"] = "effect"
    payload: EffectPayload


class DisplayPayload(_Model):
    background: Background


class Display(_Model):
    v: Literal[0] = PROTOCOL_VERSION
    type: Literal["display"] = "display"
    payload: DisplayPayload


type ServerMessage = Speech | Tension | Say | Effect | Display
SERVER_MESSAGE_TYPES = (Speech, Tension, Say, Effect, Display)
