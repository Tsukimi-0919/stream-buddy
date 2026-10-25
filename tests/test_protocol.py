import json

import pytest
from pydantic import ValidationError

from stream_buddy.protocol import (
    Display,
    DisplayPayload,
    Effect,
    EffectPayload,
    Hello,
    Say,
    SayPayload,
    Speech,
    SpeechPayload,
    Tension,
    TensionPayload,
)


def test_say_max_length() -> None:
    say = Say(payload=SayPayload(line_id="greet", text="あ" * 80))
    assert len(say.payload.text) == 80


def test_say_81_chars_is_rejected() -> None:
    with pytest.raises(ValidationError):
        SayPayload(line_id="greet", text="あ" * 81)


def test_say_empty_text_is_rejected() -> None:
    with pytest.raises(ValidationError):
        SayPayload(line_id="greet", text="")


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (Speech(payload=SpeechPayload(speaking=True)), {"speaking": True}),
        (Tension(payload=TensionPayload(level="high")), {"level": "high"}),
        (Say(payload=SayPayload(line_id="a", text="やあ")), {"line_id": "a", "text": "やあ"}),
        (Effect(payload=EffectPayload(kind="death")), {"kind": "death"}),
        (Display(payload=DisplayPayload(background="chroma")), {"background": "chroma"}),
    ],
)
def test_server_message_json(message: Speech, expected: dict[str, object]) -> None:
    data = json.loads(message.model_dump_json())
    assert data == {"v": 0, "type": message.type, "payload": expected}


def test_hello_is_valid() -> None:
    hello = Hello.model_validate_json(
        '{"v": 0, "type": "hello", "payload": {"page_version": "0.1.0"}}'
    )
    assert hello.payload.page_version == "0.1.0"


@pytest.mark.parametrize(
    "raw",
    [
        '{"v": 1, "type": "hello", "payload": {"page_version": "0.1.0"}}',
        '{"type": "hello", "payload": {"page_version": "0.1.0"}}',
        '{"v": 0, "type": "say", "payload": {"line_id": "a", "text": "b"}}',
        '{"v": 0, "type": "hello", "payload": {"page_version": "0.1.0"}, "x": 1}',
        '{"v": 0, "type": "hello", "payload": {"page_version": "0.1.0", "x": 1}}',
        '{"v": 0, "type": "hello", "payload": {"page_version": 1}}',
        "not json",
    ],
)
def test_invalid_client_messages(raw: str) -> None:
    with pytest.raises(ValidationError):
        Hello.model_validate_json(raw)


def test_messages_are_frozen() -> None:
    say = Say(payload=SayPayload(line_id="a", text="b"))
    with pytest.raises(ValidationError):
        say.type = "speech"  # type: ignore[assignment]
