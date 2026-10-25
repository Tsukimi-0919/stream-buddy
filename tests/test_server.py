from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from stream_buddy import server
from stream_buddy.__main__ import main
from stream_buddy.config import Background, Config, DisplayConfig
from stream_buddy.protocol import Hello, Say, SayPayload, Speech, SpeechPayload

PORT = 8765
TOKEN = "test-token-0123456789"  # noqa: S105
BASE = f"http://127.0.0.1:{PORT}"
WS = f"ws://127.0.0.1:{PORT}"
ORIGIN = {"origin": BASE}
HELLO = '{"v": 0, "type": "hello", "payload": {"page_version": "0.1.0"}}'


@pytest.fixture
def hub() -> server.Hub:
    return server.Hub()


@pytest.fixture
def client(hub: server.Hub) -> Iterator[TestClient]:
    app = server.create_app(Config(), TOKEN, hub)
    with TestClient(app, base_url=BASE) as c:
        yield c


def broadcast(client: TestClient, hub: server.Hub, message: Any) -> None:
    client.portal.call(hub.broadcast, message)  # type: ignore[union-attr]


# 待ち受けと起動


def test_host_is_loopback() -> None:
    assert server.HOST == "127.0.0.1"


def test_serve_passes_host_to_uvicorn(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(server.uvicorn, "run", lambda app, **kw: calls.append(kw))
    server.serve(Config(), TOKEN)
    assert calls[0]["host"] == "127.0.0.1"
    assert calls[0]["port"] == PORT
    assert calls[0]["ws_max_size"] == 4096
    assert calls[0]["access_log"] is False


def test_main_starts_server_and_prints_url_once(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(server.uvicorn, "run", lambda app, **kw: calls.append(kw))
    config_path = tmp_path / "config.toml"
    config_path.write_text("[server]\nport = 9000\n", encoding="utf-8")

    assert main(["--config", str(config_path)]) == 0

    assert calls[0]["host"] == "127.0.0.1"
    assert calls[0]["port"] == 9000
    out = capsys.readouterr().out
    assert out.count("http://127.0.0.1:9000/overlay?token=") == 1
    assert "この URL を配信画面に映さないでください" in out


def test_main_uses_defaults_without_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(server.uvicorn, "run", lambda app, **kw: calls.append(kw))
    monkeypatch.chdir(tmp_path)
    assert main([]) == 0
    assert calls[0]["port"] == PORT


def test_main_config_error_exits_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(server.uvicorn, "run", lambda app, **kw: calls.append(kw))
    config_path = tmp_path / "config.toml"
    config_path.write_text("[server]\nport = 80\n", encoding="utf-8")

    assert main(["--config", str(config_path)]) == 2
    assert calls == []
    assert "[server] port" in capsys.readouterr().err


@pytest.mark.parametrize(("argv", "expected"), [([], False), (["--demo"], True)])
def test_main_demo_option(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, argv: list[str], expected: bool
) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(server, "serve", lambda config, token, **kw: calls.append(kw))
    monkeypatch.chdir(tmp_path)
    assert main(argv) == 0
    assert calls == [{"demo": expected}]


def test_tokens_differ_each_time() -> None:
    assert server.new_token() != server.new_token()
    assert len(server.new_token()) >= 43


# HTTP


def test_overlay_with_token(client: TestClient) -> None:
    response = client.get(f"/overlay?token={TOKEN}")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "stream-buddy" in response.text


@pytest.mark.parametrize("query", ["", "?token=", "?token=wrong", "?token=あ"])
def test_overlay_without_valid_token_is_404(client: TestClient, query: str) -> None:
    assert client.get(f"/overlay{query}").status_code == 404


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json", "/", "/static/x.css"])
def test_other_paths_are_404(client: TestClient, path: str) -> None:
    assert client.get(path).status_code == 404


def test_static_files_without_token(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<p>page</p>", encoding="utf-8")
    (tmp_path / "static").mkdir()
    (tmp_path / "static" / "app.css").write_text("p {}", encoding="utf-8")
    monkeypatch.setattr(server, "OVERLAY_DIR", tmp_path)
    app = server.create_app(Config(), TOKEN)
    with TestClient(app, base_url=BASE) as c:
        response = c.get("/static/app.css")
        assert response.status_code == 200
        assert response.headers["x-content-type-options"] == "nosniff"
        # static の外にある index.html はトークンなしでは取れない
        assert c.get("/static/../index.html").status_code == 404
        assert c.get("/static/%2e%2e/index.html").status_code == 404


@pytest.mark.parametrize(
    "host", ["evil.example", "evil.example:8765", "localhost:8765", "127.0.0.1:9999", "127.0.0.1"]
)
def test_wrong_host_is_400(client: TestClient, host: str) -> None:
    response = client.get(f"/overlay?token={TOKEN}", headers={"host": host})
    assert response.status_code == 400
    assert "stream-buddy" not in response.text


@pytest.mark.parametrize(
    ("path", "headers"),
    [
        (f"/overlay?token={TOKEN}", {}),
        ("/overlay", {}),
        ("/docs", {}),
        ("/static/x.css", {}),
        ("/overlay", {"host": "evil.example"}),
    ],
)
def test_security_headers_on_all_responses(
    client: TestClient, path: str, headers: dict[str, str]
) -> None:
    response = client.get(path, headers=headers)
    assert response.headers["content-security-policy"] == (
        "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "connect-src ws://127.0.0.1:8765; base-uri 'none'; form-action 'none'; "
        "frame-ancestors 'none'"
    )
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store"


# WebSocket の接続


def test_ws_connects_and_survives_hello(client: TestClient, hub: server.Hub) -> None:
    with client.websocket_connect(f"{WS}/ws?token={TOKEN}", headers=ORIGIN) as ws:
        ws.send_text(HELLO)
        assert ws.receive_json()["type"] == "display"
        broadcast(client, hub, Speech(payload=SpeechPayload(speaking=True)))
        assert ws.receive_json()["type"] == "speech"


@pytest.mark.parametrize("background", ["transparent", "chroma"])
def test_hello_is_answered_with_display(background: Background) -> None:
    config = Config(display=DisplayConfig(background=background))
    app = server.create_app(config, TOKEN)
    with (
        TestClient(app, base_url=BASE) as c,
        c.websocket_connect(f"{WS}/ws?token={TOKEN}", headers=ORIGIN) as ws,
    ):
        ws.send_text(HELLO)
        assert ws.receive_json() == {
            "v": 0,
            "type": "display",
            "payload": {"background": background},
        }


def test_display_reply_goes_only_to_the_sender(client: TestClient, hub: server.Hub) -> None:
    url = f"{WS}/ws?token={TOKEN}"
    with (
        client.websocket_connect(url, headers=ORIGIN) as a,
        client.websocket_connect(url, headers=ORIGIN) as b,
    ):
        a.send_text(HELLO)
        assert a.receive_json()["type"] == "display"
        broadcast(client, hub, Speech(payload=SpeechPayload(speaking=True)))
        # b は hello を送っていないので、最初に届くのは broadcast したメッセージ
        assert b.receive_json()["type"] == "speech"
        assert a.receive_json()["type"] == "speech"


@pytest.mark.parametrize(
    ("query", "headers"),
    [
        ("", ORIGIN),
        ("?token=wrong", ORIGIN),
        ("?token=あ", ORIGIN),
        (f"?token={TOKEN}", {}),
        (f"?token={TOKEN}", {"origin": "http://evil.example"}),
        (f"?token={TOKEN}", {"origin": "http://localhost:8765"}),
        (f"?token={TOKEN}", {"origin": "http://127.0.0.1:8765/"}),
        (f"?token={TOKEN}", {"origin": "null"}),
    ],
)
def test_ws_rejected(client: TestClient, query: str, headers: dict[str, str]) -> None:
    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect(f"{WS}/ws{query}", headers=headers),
    ):
        pass


@pytest.mark.parametrize("host", ["evil.example:8765", "localhost:8765", "127.0.0.1:9999"])
def test_ws_wrong_host_is_rejected_without_accept(
    client: TestClient, hub: server.Hub, host: str
) -> None:
    headers = {**ORIGIN, "host": host}
    # HTTP の 400 応答 (WebSocketDenialResponse) ではなく、accept せずに閉じる
    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect(f"{WS}/ws?token={TOKEN}", headers=headers),
    ):
        pass
    # 拒否した接続は数に入らず、正しい接続は2本まで受け入れられる
    url = f"{WS}/ws?token={TOKEN}"
    with (
        client.websocket_connect(url, headers=ORIGIN),
        client.websocket_connect(url, headers=ORIGIN),
    ):
        pass


def test_ws_third_connection_is_rejected(client: TestClient, hub: server.Hub) -> None:
    url = f"{WS}/ws?token={TOKEN}"
    with (
        client.websocket_connect(url, headers=ORIGIN),
        client.websocket_connect(url, headers=ORIGIN),
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect(url, headers=ORIGIN),
    ):
        pass
    # 切断後は再び接続できる
    with client.websocket_connect(url, headers=ORIGIN) as ws:
        broadcast(client, hub, Speech(payload=SpeechPayload(speaking=False)))
        assert ws.receive_json()["payload"] == {"speaking": False}


# WebSocket の受信


@pytest.mark.parametrize(
    "bad",
    [
        '{"v": 0, "type": "unknown", "payload": {}}',
        '{"v": 0, "type": "hello", "payload": {"page_version": "0.1.0"}, "extra": 1}',
        "{broken json",
        '{"v": 0, "type": "say", "payload": {"line_id": "a", "text": "b"}}',
    ],
)
def test_ws_invalid_messages_are_dropped(client: TestClient, hub: server.Hub, bad: str) -> None:
    with client.websocket_connect(f"{WS}/ws?token={TOKEN}", headers=ORIGIN) as ws:
        ws.send_text(bad)
        ws.send_bytes(b"\x00\x01")
        ws.send_text(HELLO)
        # 捨てたメッセージには何も返さず、hello にだけ返す
        assert ws.receive_json()["type"] == "display"
        broadcast(client, hub, Say(payload=SayPayload(line_id="a", text="まだいるよ")))
        assert ws.receive_json()["payload"]["text"] == "まだいるよ"


def test_ws_invalid_message_log_has_no_content(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    private_text = "ひみつの発話"
    with client.websocket_connect(f"{WS}/ws?token={TOKEN}", headers=ORIGIN) as ws:
        ws.send_text(f'{{"v": 0, "type": "{private_text}", "{private_text}": 1}}')
        ws.send_text(HELLO)
    assert "破棄しました" in caplog.text
    assert private_text not in caplog.text


def test_ws_too_big_message_closes(client: TestClient) -> None:
    with client.websocket_connect(f"{WS}/ws?token={TOKEN}", headers=ORIGIN) as ws:
        ws.send_text("a" * 4097)
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_text()
    assert exc.value.code == 1009


def test_ws_message_at_limit_is_kept(client: TestClient, hub: server.Hub) -> None:
    with client.websocket_connect(f"{WS}/ws?token={TOKEN}", headers=ORIGIN) as ws:
        ws.send_text("a" * 4096)
        broadcast(client, hub, Speech(payload=SpeechPayload(speaking=True)))
        assert ws.receive_json()["type"] == "speech"


# broadcast


def test_broadcast_reaches_all_pages_as_protocol_json(client: TestClient, hub: server.Hub) -> None:
    url = f"{WS}/ws?token={TOKEN}"
    with (
        client.websocket_connect(url, headers=ORIGIN) as a,
        client.websocket_connect(url, headers=ORIGIN) as b,
    ):
        broadcast(client, hub, Say(payload=SayPayload(line_id="greet", text="こんにちは")))
        expected = {"v": 0, "type": "say", "payload": {"line_id": "greet", "text": "こんにちは"}}
        assert a.receive_json() == expected
        assert b.receive_json() == expected


def test_broadcast_rejects_client_message(client: TestClient, hub: server.Hub) -> None:
    hello = Hello.model_validate_json(HELLO)
    with pytest.raises(TypeError):
        broadcast(client, hub, hello)


def test_broadcast_without_connections(client: TestClient, hub: server.Hub) -> None:
    broadcast(client, hub, Speech(payload=SpeechPayload(speaking=True)))
