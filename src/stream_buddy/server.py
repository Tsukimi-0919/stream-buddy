"""ページの配信と WebSocket のローカルサーバー。

ここが外部 (ブラウザで開いた任意のサイト) との境界になる。
守りは次のとおり。
- 127.0.0.1 だけで待ち受ける (SR-01)
- Host ヘッダーを確認する (DNS リバインディング対策)
- ページと WebSocket はトークンで、WebSocket はさらに Origin で認証する (SR-02)
- 受信メッセージはスキーマで検証し、合わないものは捨てる (SR-03)
- すべての HTTP 応答に CSP などのヘッダーを付ける (SR-04)
"""

import asyncio
import contextlib
import logging
import mimetypes
import secrets
from collections.abc import AsyncIterator
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from stream_buddy import demo as demo_mode
from stream_buddy.config import Config
from stream_buddy.protocol import (
    MAX_MESSAGE_BYTES,
    SERVER_MESSAGE_TYPES,
    Display,
    DisplayPayload,
    Hello,
    ServerMessage,
)

HOST = "127.0.0.1"
MAX_CONNECTIONS = 2
OVERLAY_DIR = Path(__file__).parent / "overlay"

# Windows ではレジストリの設定で .js が text/plain になることがあり、
# nosniff のもとではスクリプトが動かなくなるため、明示しておく
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")

# WebSocket の close コード: メッセージが大きすぎる
_CLOSE_TOO_BIG = 1009

logger = logging.getLogger(__name__)


def new_token() -> str:
    """起動ごとのトークンを作る。ファイルやログには保存しない。"""
    return secrets.token_urlsafe(32)


def overlay_url(port: int, token: str) -> str:
    return f"http://{HOST}:{port}/overlay?token={token}"


def security_headers(port: int) -> dict[str, str]:
    csp = (
        "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        f"connect-src ws://{HOST}:{port}; base-uri 'none'; form-action 'none'; "
        "frame-ancestors 'none'"
    )
    return {
        "Content-Security-Policy": csp,
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "Cache-Control": "no-store",
    }


class Hub:
    """接続中のページを管理し、メッセージを送る。"""

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()

    def try_add(self, websocket: WebSocket) -> bool:
        if len(self._connections) >= MAX_CONNECTIONS:
            return False
        self._connections.add(websocket)
        return True

    def remove(self, websocket: WebSocket) -> None:
        self._connections.discard(websocket)

    async def broadcast(self, message: ServerMessage) -> None:
        """接続中のすべてのページに送る。サーバー → ページのメッセージだけを受け付ける。"""
        if not isinstance(message, SERVER_MESSAGE_TYPES):
            raise TypeError("サーバーからページへのメッセージではありません")
        data = message.model_dump_json()
        for websocket in list(self._connections):
            try:
                await websocket.send_text(data)
            except Exception:
                # 送信中に切れた接続は、受信側の処理で片付ける
                logger.info("切断済みの接続への送信をスキップしました")


class _GuardMiddleware:
    """Host ヘッダーを確認し、すべての HTTP 応答にセキュリティヘッダーを付ける。"""

    def __init__(self, app: ASGIApp, port: int) -> None:
        self.app = app
        self.expected_host = f"{HOST}:{port}"
        self.headers = security_headers(port)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] in ("http.response.start", "websocket.http.response.start"):
                headers = MutableHeaders(scope=message)
                for name, value in self.headers.items():
                    headers[name] = value
            await send(message)

        if Headers(scope=scope).get("host") != self.expected_host:
            logger.warning("Host ヘッダーが一致しないリクエストを拒否しました")
            if scope["type"] == "http":
                response = PlainTextResponse("Bad Request", status_code=400)
                await response(scope, receive, send_with_headers)
            else:
                # 他の WebSocket の拒否と同じく、accept せずに閉じる
                await WebSocket(scope, receive, send).close()
            return
        await self.app(scope, receive, send_with_headers)


def create_app(
    config: Config, token: str, hub: Hub | None = None, *, demo: bool = False
) -> FastAPI:
    port = config.server.port
    expected_origin = f"http://{HOST}:{port}"
    hub = hub if hub is not None else Hub()
    # hello への返信。接続したページに現在の背景を知らせる
    initial_display = Display(payload=DisplayPayload(background=config.display.background))

    def token_ok(given: str) -> bool:
        return secrets.compare_digest(given.encode(), token.encode())

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        if not demo:
            yield
            return
        task = asyncio.create_task(demo_mode.run_demo(hub.broadcast))
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    app = FastAPI(
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        # 外部へ通信しないため、FastAPI 組み込みの OpenTelemetry はすべて止める
        telemetry={
            "tracing": False,
            "metrics": False,
            "logs": False,
            "operation_spans": False,
            "auto_configure": False,
        },
    )
    app.state.hub = hub
    app.add_middleware(_GuardMiddleware, port=port)
    # ページ用の CSS・JS・画像。秘密情報を含まないのでトークン不要
    static_dir = OVERLAY_DIR / "static"
    if static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=static_dir))

    @app.get("/overlay")
    async def overlay(token: str = "") -> Response:
        if not token_ok(token):
            # トークンが違うときは、ページの存在を知らせない
            return PlainTextResponse("Not Found", status_code=404)
        return FileResponse(OVERLAY_DIR / "index.html", media_type="text/html")

    @app.websocket("/ws")
    async def ws(websocket: WebSocket, token: str = "") -> None:
        origin = websocket.headers.get("origin")
        # 理由は伝えずに、accept せず閉じる
        if not token_ok(token) or origin != expected_origin or not hub.try_add(websocket):
            await websocket.close()
            return
        try:
            await websocket.accept()
            await _receive_loop(websocket, initial_display)
        finally:
            hub.remove(websocket)

    return app


async def _receive_loop(websocket: WebSocket, hello_reply: ServerMessage) -> None:
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return
        text: str | None = message.get("text")
        raw: bytes = text.encode() if text is not None else (message.get("bytes") or b"")
        if len(raw) > MAX_MESSAGE_BYTES:
            logger.warning("上限を超えるメッセージを受信したため接続を閉じました")
            await websocket.close(code=_CLOSE_TOO_BIG)
            return
        if text is None:
            logger.warning("バイナリのメッセージを破棄しました")
            continue
        try:
            Hello.model_validate_json(raw)
        except ValidationError as e:
            # 中身はログに残さず、エラーの種類だけを残す
            reasons = ", ".join(sorted({err["type"] for err in e.errors()}))
            logger.warning("形の合わないメッセージを破棄しました: %s", reasons)
            continue
        logger.info("ページから hello を受信しました")
        await websocket.send_text(hello_reply.model_dump_json())


def serve(config: Config, token: str, *, demo: bool = False) -> None:
    """サーバーを起動する。待ち受けアドレスは常に HOST (SR-01)。"""
    uvicorn.run(
        create_app(config, token, demo=demo),
        host=HOST,
        port=config.server.port,
        ws="websockets-sansio",
        ws_max_size=MAX_MESSAGE_BYTES,
        # アクセスログや接続ログには URL のトークンが出るため、warning 未満は出さない
        access_log=False,
        log_level="warning",
    )
