import itertools
import re
from collections.abc import Iterator
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from stream_buddy import server
from stream_buddy.config import Config
from stream_buddy.state import constants

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


# 画面演出 (死亡・クリア) と置き場所 (pos=)

KINDS = ("death", "clear")
# 演出の動き (prefers-reduced-motion のときは止める)
MOTION_KEYFRAMES = ("effect-sink", "effect-tear", "effect-spread", "effect-jump", "effect-fall")
# 明るさを変えるアニメーション
BRIGHTNESS_KEYFRAMES = ("effect-dim", "effect-glow", "effect-fade")


def css_rules(css: str) -> list[tuple[str, str]]:
    """(セレクター, 中身) の一覧。@media の中の規則も含め、@keyframes は除く。"""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    css = re.sub(r"@keyframes[^{]*\{(?:[^{}]*\{[^}]*\})*\s*\}", "", css)
    css = re.sub(r"@media[^{]*\{", "", css)
    return [(sel.strip(), body) for sel, body in re.findall(r"([^{}]+)\{([^}]*)\}", css)]


def effect_rules(css: str) -> list[tuple[str, str]]:
    return [(sel, body) for sel, body in css_rules(css) if "[data-effect=" in sel]


def reduced_motion_css() -> str:
    """@media (prefers-reduced-motion: reduce) の中身だけをつなげる。"""
    blocks = re.findall(
        r"@media \(prefers-reduced-motion: reduce\) \{((?:[^{}]*\{[^}]*\})*)\s*\}", STYLE_CSS
    )
    assert blocks
    return "".join(blocks)


def keyframes(name: str) -> dict[float, str]:
    """@keyframes の区切り (0〜1) と中身。"""
    match = re.search(rf"@keyframes {name} \{{((?:[^{{}}]*\{{[^}}]*\}})*)\s*\}}", STYLE_CSS)
    assert match, name
    stops: dict[float, str] = {}
    for selector, body in re.findall(r"([\d%, ]+)\{([^}]*)\}", match.group(1)):
        for stop in selector.split(","):
            stops[float(stop.strip().rstrip("%")) / 100] = body.strip()
    return stops


def effect_duration_s() -> float:
    match = re.search(r"--effect-duration:\s*([\d.]+)s;", STYLE_CSS)
    assert match
    return float(match.group(1))


@pytest.mark.parametrize("kind", KINDS)
def test_style_css_has_effect_for_each_kind(kind: str) -> None:
    rules = [(sel, body) for sel, body in effect_rules(STYLE_CSS) if f'"{kind}"' in sel]
    assert any("animation:" in body for _, body in rules)
    # 画面全体の層とメンダコの両方に演出がある
    selectors = " ".join(sel for sel, _ in rules)
    assert ".buddy-motion" in selectors
    assert (".effect-vignette" if kind == "death" else ".effect-rainbow") in selectors
    assert (".eyes-sad" if kind == "death" else ".sparkles") in selectors


def test_effect_duration_matches_constants() -> None:
    assert STYLE_CSS.count("--effect-duration:") == 1  # 1 か所にまとめる
    assert effect_duration_s() * 1000 == constants.EFFECT_MS
    assert f"const EFFECT_DURATION_MS = {constants.EFFECT_MS};" in APP_JS


def test_effect_animations_use_effect_duration_and_do_not_repeat() -> None:
    rules = effect_rules(STYLE_CSS)
    assert rules
    for selector, body in rules:
        assert "infinite" not in body, selector
        if "animation:" in body and "animation: none;" not in body:
            # 長さは --effect-duration だけで決める (数字の秒を書かない)
            assert "var(--effect-duration)" in body, selector
            assert not re.search(r"\b\d+(\.\d+)?m?s\b", body), selector
    pieces = [body for sel, body in css_rules(STYLE_CSS) if sel.startswith(".confetti-piece")]
    assert pieces
    assert all("infinite" not in body for body in pieces)


def test_reduced_motion_stops_effect_motion() -> None:
    rules = effect_rules(reduced_motion_css())
    # 紙吹雪を出さない
    assert any(".confetti" in sel and "display: none" in body for sel, body in rules)
    # 跳ねる・沈む・広がる・涙を止め、色の変化 (暗くなる・明るくなる・色あせ) だけを残す
    for target in ('"clear"] .buddy-motion', '"death"] .buddy-motion', '"death"] .tear'):
        assert any(target in sel for sel, _ in rules), target
    for selector, body in rules:
        assert not any(name in body for name in MOTION_KEYFRAMES), selector
    assert any("effect-fade" in body for _, body in rules)
    assert any("effect-glow" in body for _, body in rules)


def test_motion_keyframes_change_only_transform() -> None:
    names = re.findall(r"@keyframes (effect-[\w-]+)", STYLE_CSS)
    motion = [n for n in names if n.startswith(MOTION_KEYFRAMES)]
    assert len(motion) >= len(MOTION_KEYFRAMES)
    for name in motion:
        assert all(body.startswith("transform:") for body in keyframes(name).values()), name


@pytest.mark.parametrize("name", BRIGHTNESS_KEYFRAMES)
def test_brightness_changes_take_at_least_half_a_second(name: str) -> None:
    stops = sorted(keyframes(name).items())
    assert (stops[0][0], stops[-1][0]) == (0, 1)
    duration = effect_duration_s()
    pairs = list(itertools.pairwise(stops))
    for (start, before), (end, after) in pairs:
        if before != after:
            assert (end - start) * duration >= 0.5, (name, start, end)
    # 点滅しない (1 秒に 3 回より多く変わらない)
    changes = sum(1 for (_, before), (_, after) in pairs if before != after)
    assert changes / duration <= 3
    # steps() で一気に切り替えない
    uses = [body for _, body in css_rules(STYLE_CSS) if name in body]
    assert uses
    assert all("steps(" not in body for body in uses)


def test_effect_layer_is_behind_bubble_and_buddy() -> None:
    rules = dict(css_rules(STYLE_CSS))
    assert "z-index: 0;" in rules[".effect"]
    assert "pointer-events: none;" in rules[".effect"]
    assert "z-index: 1;" in rules[".stage"]
    assert INDEX_HTML.index('class="effect"') < INDEX_HTML.index('class="stage"')


def test_overlay_html_has_effect_elements_without_inline_style() -> None:
    checker = _PageChecker()
    checker.feed(INDEX_HTML)
    assert checker.problems == []
    assert INDEX_HTML.count('<span class="confetti-piece"></span>') == 30
    for name in ("effect-vignette", "effect-rainbow", "confetti", "buddy-motion", "eyes-sad"):
        assert f'class="{name}"' in INDEX_HTML
    assert 'data-pos="center"' in INDEX_HTML


def test_app_js_shows_effect_and_removes_it_after_duration() -> None:
    assert "apply: (p) => showEffect(p.kind)," in APP_JS
    show = APP_JS.split("function showEffect(kind) {")[1].split("\n  }\n")[0]
    # 出し直し: 前のタイマーを止め、外してから付け直す
    steps = [
        "clearTimeout(effectTimer);",
        "delete body.dataset.effect;",
        "void body.offsetWidth;",
        "body.dataset.effect = kind;",
        "effectTimer = setTimeout(hideEffect, EFFECT_DURATION_MS);",
    ]
    positions = [show.index(step) for step in steps]
    assert positions == sorted(positions)
    hide = APP_JS.split("function hideEffect() {")[1].split("\n  }\n")[0]
    assert "delete body.dataset.effect;" in hide
    # 受け付ける種類は death と clear だけ (今までどおり)
    assert 'valid: (p) => ["death", "clear"].includes(p.kind),' in APP_JS


def test_app_js_accepts_only_known_positions() -> None:
    assert (
        'const POSITIONS = ["center", "bottom-right", "bottom-left", "top-right", "top-left"];'
        in APP_JS
    )
    assert 'const pos = params.get("pos");' in APP_JS
    assert 'body.dataset.pos = POSITIONS.includes(pos) ? pos : "center";' in APP_JS
    # pos は見た目にだけ使い、サーバーへは送らない
    code = [line for line in APP_JS.splitlines() if not line.strip().startswith("//")]
    assert [line.strip() for line in code if re.search(r"\bpos\b", line)] == [
        'const pos = params.get("pos");',
        'body.dataset.pos = POSITIONS.includes(pos) ? pos : "center";',
    ]


@pytest.mark.parametrize("pos", ["top-left", "top-right", "bottom-left", "bottom-right"])
def test_style_css_places_buddy_for_each_position(pos: str) -> None:
    rules = [body for sel, body in css_rules(STYLE_CSS) if f'body[data-pos="{pos}"] .stage' in sel]
    horizontal = "flex-start" if pos.endswith("left") else "flex-end"
    assert any(f"align-items: {horizontal};" in body for body in rules)
    if pos.startswith("top"):
        assert any("justify-content: flex-start;" in body for body in rules)


def test_overlay_with_pos_param_is_served(client: TestClient) -> None:
    response = client.get(f"/overlay?token={TOKEN}&pos=bottom-right")
    assert response.status_code == 200
    assert 'data-pos="center"' in response.text  # 置き場所は app.js が URL から決める
