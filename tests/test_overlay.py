import re
from collections.abc import Iterator
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from stream_buddy import server
from stream_buddy.config import Config

PORT = 8765
TOKEN = "test-token-0123456789"  # noqa: S105
BASE = f"http://127.0.0.1:{PORT}"
WS = f"ws://127.0.0.1:{PORT}"
ORIGIN = {"origin": BASE}
STATIC_DIR = Path(server.OVERLAY_DIR) / "static"
APP_JS = (STATIC_DIR / "app.js").read_text(encoding="utf-8")


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = server.create_app(Config(), TOKEN)
    with TestClient(app, base_url=BASE) as c:
        yield c


class _PageChecker(HTMLParser):
    """CSP で止められる書き方を集める。"""

    def __init__(self) -> None:
        super().__init__()
        self.problems: list[str] = []
        self._in_script = False
        self.ids: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        names = {name for name, _ in attrs}
        for name, value in attrs:
            if name == "id" and value:
                self.ids.add(value)
            if name.startswith("on"):
                self.problems.append(f"<{tag} {name}>")
        if "style" in names:
            self.problems.append(f"<{tag} style>")
        if tag == "style":
            self.problems.append("<style>")
        if tag == "script":
            if "src" not in names:
                self.problems.append("<script> without src")
            self._in_script = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._in_script = False

    def handle_data(self, data: str) -> None:
        if self._in_script and data.strip():
            self.problems.append("inline script content")


# ページの HTML


def test_overlay_html_has_no_inline_script_or_style(client: TestClient) -> None:
    response = client.get(f"/overlay?token={TOKEN}")
    assert response.status_code == 200
    checker = _PageChecker()
    checker.feed(response.text)
    assert checker.problems == []
    assert '<script src="/static/app.js"' in response.text
    assert '<link rel="stylesheet" href="/static/style.css">' in response.text


def test_overlay_html_has_elements_used_by_app_js(client: TestClient) -> None:
    checker = _PageChecker()
    checker.feed(client.get(f"/overlay?token={TOKEN}").text)
    used = set(re.findall(r'getElementById\("([^"]+)"\)', APP_JS))
    assert used
    assert used <= checker.ids


def test_overlay_html_has_two_mouths(client: TestClient) -> None:
    html = client.get(f"/overlay?token={TOKEN}").text
    assert "mouth-closed" in html
    assert "mouth-open" in html


# app.js


@pytest.mark.parametrize(
    "forbidden",
    [
        "innerHTML",
        "outerHTML",
        "insertAdjacentHTML",
        "document.write",
        "eval(",
        "Function(",
        # トークンを出力しないよう、console の利用自体を禁止する
        "console.",
        "alert(",
        "localStorage",
        "sessionStorage",
    ],
)
def test_app_js_does_not_use(forbidden: str) -> None:
    assert forbidden not in APP_JS


def test_app_js_timers_take_functions_not_strings() -> None:
    assert not re.search(r"set(Timeout|Interval)\(\s*[\"'`]", APP_JS)
    assert "setInterval" not in APP_JS


def test_app_js_uses_text_content() -> None:
    assert "textContent" in APP_JS


def test_app_js_connects_to_loopback_with_same_port() -> None:
    assert '"ws://127.0.0.1:" + window.location.port + "/ws?token="' in APP_JS


def test_style_css_does_not_load_external_resources() -> None:
    css = (STATIC_DIR / "style.css").read_text(encoding="utf-8")
    assert "url(" not in css
    assert "@import" not in css


# 静的ファイル


@pytest.mark.parametrize(
    ("path", "content_type"),
    [("/static/app.js", "text/javascript"), ("/static/style.css", "text/css")],
)
def test_static_files(client: TestClient, path: str, content_type: str) -> None:
    response = client.get(path)
    assert response.status_code == 200
    assert response.headers["content-type"].split(";")[0] == content_type
    assert (
        response.headers["content-security-policy"]
        == server.security_headers(PORT)["Content-Security-Policy"]
    )
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store"


# デモモード


def test_no_demo_without_option(client: TestClient) -> None:
    with client.websocket_connect(f"{WS}/ws?token={TOKEN}", headers=ORIGIN) as ws:
        ws.send_text('{"v": 0, "type": "hello", "payload": {"page_version": "0.1.0"}}')
        # デモがなければ、最初に届くのは hello への返信
        assert ws.receive_json()["type"] == "display"


# テンションの見た目と、確認用の表示 (debug=1)

STYLE_CSS = (STATIC_DIR / "style.css").read_text(encoding="utf-8")
INDEX_HTML = (Path(server.OVERLAY_DIR) / "index.html").read_text(encoding="utf-8")


@pytest.mark.parametrize("level", ["calm", "normal", "high"])
def test_style_css_has_look_for_each_tension(level: str) -> None:
    rules = re.findall(rf'\.buddy\[data-tension="{level}"\][^{{]*\{{([^}}]*)\}}', STYLE_CSS)
    assert any("animation:" in body for body in rules)


def test_style_css_changes_color_and_eyes_by_tension() -> None:
    # Calm は色と半目、High は色と光とキラキラ
    assert '.buddy[data-tension="calm"] .body' in STYLE_CSS
    assert '.buddy[data-tension="calm"] .eyelids' in STYLE_CSS
    assert '.buddy[data-tension="high"] .body' in STYLE_CSS
    assert '.buddy[data-tension="high"] .sparkles' in STYLE_CSS
    assert "drop-shadow" in STYLE_CSS
    assert "transition:" in STYLE_CSS


def test_style_css_reduces_motion() -> None:
    assert "@media (prefers-reduced-motion: reduce)" in STYLE_CSS
    reduced = STYLE_CSS.split("@media (prefers-reduced-motion: reduce)")[1]
    for level in ("calm", "normal", "high"):
        assert f'.buddy[data-tension="{level}"]' in reduced


def test_style_css_has_no_inline_or_external_style() -> None:
    assert "<style" not in STYLE_CSS
    assert "url(" not in STYLE_CSS


def test_overlay_html_has_eye_shapes_for_each_tension() -> None:
    checker = _PageChecker()
    checker.feed(INDEX_HTML)
    assert checker.problems == []  # インラインのスタイル・style 属性はない
    assert 'class="eyelids"' in INDEX_HTML
    assert 'class="sparkles"' in INDEX_HTML
    assert 'id="debug-tension"' in INDEX_HTML


def test_overlay_with_debug_param_is_served(client: TestClient) -> None:
    response = client.get(f"/overlay?token={TOKEN}&debug=1")
    assert response.status_code == 200
    assert 'id="debug-tension" class="debug-tension" hidden' in response.text


def test_app_js_shows_debug_tension_only_with_debug_1() -> None:
    assert 'params.get("debug") === "1"' in APP_JS
    assert "debugTension.textContent = level;" in APP_JS
    # debug の表示に使うのは textContent と hidden だけ
    uses = set(re.findall(r"debugTension\.(\w+)", APP_JS))
    assert uses == {"textContent", "hidden"}


def test_app_js_does_not_rewrite_svg() -> None:
    # 目の形は style.css で切り替える。JavaScript で SVG の要素を作ったり書き換えたりしない
    for forbidden in ("createElement", "setAttribute", "appendChild", ".style"):
        assert forbidden not in APP_JS
