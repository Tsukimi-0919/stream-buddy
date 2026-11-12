"""メンダコの絵 (T-19)：体は画像、顔は SVG。"""

import re
import struct
import zlib
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
ROOT = Path(__file__).parent.parent
OVERLAY_DIR = Path(server.OVERLAY_DIR)
IMAGE_URL = "/static/img/mendako-body.png"
IMAGE = OVERLAY_DIR / "static" / "img" / "mendako-body.png"
INDEX_HTML = (OVERLAY_DIR / "index.html").read_text(encoding="utf-8")
STYLE_CSS = (OVERLAY_DIR / "static" / "style.css").read_text(encoding="utf-8")
IMAGE_SIZE = 512
IMAGE_MAX_BYTES = 300 * 1024
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# HTML の終了タグがない要素 (SVG の <image .../> などは handle_startendtag に来る)
VOID_TAGS = {"meta", "link", "br", "img", "input", "hr"}


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = server.create_app(Config(), TOKEN)
    with TestClient(app, base_url=BASE) as c:
        yield c


# PNG のヘッダー (標準ライブラリだけで読む)


def png_chunks(data: bytes) -> list[tuple[bytes, bytes]]:
    assert data[:8] == PNG_SIGNATURE
    chunks: list[tuple[bytes, bytes]] = []
    pos = 8
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        kind = data[pos + 4 : pos + 8]
        chunks.append((kind, data[pos + 8 : pos + 8 + length]))
        pos += 12 + length
    return chunks


def first_pixel_alpha(chunks: list[tuple[bytes, bytes]], width: int) -> int:
    """8 ビットの RGBA の画像で、左上の画素のアルファ。1 行目だけを戻す。"""
    raw = zlib.decompressobj().decompress(
        b"".join(body for kind, body in chunks if kind == b"IDAT")
    )
    stride = width * 4
    filter_type, row = raw[0], bytearray(raw[1 : 1 + stride])
    # 1 行目は上の行がない (0 とみなす)。左上の画素は左の画素もないので、
    # どのフィルターでも (Sub・Average・Paeth も) そのままの値になる
    assert filter_type in (0, 1, 2, 3, 4)
    return row[3]


def test_image_is_512_png_with_alpha_and_small() -> None:
    data = IMAGE.read_bytes()
    assert len(data) <= IMAGE_MAX_BYTES
    chunks = png_chunks(data)
    kind, ihdr = chunks[0]
    assert kind == b"IHDR"
    width, height, bit_depth, color_type, _, _, interlace = struct.unpack(">IIBBBBB", ihdr)
    assert (width, height) == (IMAGE_SIZE, IMAGE_SIZE)
    # 色の種類 6 = RGBA (アルファあり)、8 ビット、インターレースなし
    assert (bit_depth, color_type, interlace) == (8, 6, 0)
    assert chunks[-1][0] == b"IEND"
    # 背景 (左上の角) は透明
    assert first_pixel_alpha(chunks, width) == 0


# ページが画像を参照し、配信されること


def test_index_html_references_body_image() -> None:
    assert f'<image href="{IMAGE_URL}"' in INDEX_HTML
    assert IMAGE.is_file()
    # ほかの場所から読み込まない (CSP の img-src 'self' のまま表示できる)
    hrefs = re.findall(r'href="([^"]+)"', INDEX_HTML)
    assert all(h.startswith("/static/") for h in hrefs), hrefs


def test_body_image_is_served_with_security_headers(client: TestClient) -> None:
    response = client.get(IMAGE_URL)
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content == IMAGE.read_bytes()
    headers = server.security_headers(PORT)
    assert "img-src 'self'" in headers["Content-Security-Policy"]
    for name, value in headers.items():
        assert response.headers[name.lower()] == value, name


# SVG の組み立て


class _Tree(HTMLParser):
    """要素ごとに、祖先のクラスと id を集める。"""

    def __init__(self) -> None:
        super().__init__()
        self.stack: list[tuple[str, dict[str, str | None]]] = []
        self.found: list[tuple[str, dict[str, str | None], list[str]]] = []

    def _record(self, tag: str, attrs: list[tuple[str, str | None]]) -> dict[str, str | None]:
        attr = dict(attrs)
        ancestors: list[str] = []
        for _, a in self.stack:
            ancestors += (a.get("class") or "").split()
            if a.get("id"):
                ancestors.append(f"#{a['id']}")
        self.found.append((tag, attr, ancestors))
        return attr

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = self._record(tag, attrs)
        if tag not in VOID_TAGS:
            self.stack.append((tag, attr))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._record(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        while self.stack:
            if self.stack.pop()[0] == tag:
                break


def tree() -> _Tree:
    t = _Tree()
    t.feed(INDEX_HTML)
    return t


def test_body_image_is_inside_buddy_svg_body_group() -> None:
    images = [(attr, anc) for tag, attr, anc in tree().found if tag == "image"]
    assert len(images) == 1
    attr, ancestors = images[0]
    assert attr["href"] == IMAGE_URL
    # テンションの動き (#buddy)・演出の動き (.buddy-motion)・光 (.buddy-svg)・
    # 色 (.buddy-body) がかかる
    for name in ("#buddy", "buddy-motion", "buddy-svg", "buddy-body"):
        assert name in ancestors, name
    # 顔のグループの外 (顔の位置の調整で体が動かない)
    assert "face" not in ancestors


def test_face_parts_are_in_one_positioned_group() -> None:
    found = tree().found
    faces = [attr for tag, attr, _ in found if "face" in (attr.get("class") or "").split()]
    assert len(faces) == 1
    assert faces[0]["transform"]
    # 顔の位置と大きさは、この 1 か所の transform だけで決める
    assert INDEX_HTML.count("transform=") == 1
    for part in ("eye", "eyelids", "sparkles", "eyes-sad", "tear", "mouth-closed", "mouth-open"):
        elements = [anc for _, attr, anc in found if part in (attr.get("class") or "").split()]
        assert elements, part
        assert all("face" in anc for anc in elements), part


def test_svg_is_titled_mendako() -> None:
    assert '<title id="buddy-title">メンダコ</title>' in INDEX_HTML
    assert 'aria-labelledby="buddy-title"' in INDEX_HTML
    assert "(仮)" not in INDEX_HTML


def test_old_svg_body_is_removed() -> None:
    assert 'class="fin"' not in INDEX_HTML
    assert 'class="body"' not in INDEX_HTML
    assert "M20 135" not in INDEX_HTML
    assert not re.search(r"(^|[\s,])\.(body|fin)\b", STYLE_CSS, flags=re.MULTILINE)


# テンションと演出の見た目が、体の画像を含む要素に効いていること


def rules(css: str) -> list[tuple[str, str]]:
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    css = re.sub(r"@keyframes[^{]*\{(?:[^{}]*\{[^}]*\})*\s*\}", "", css)
    css = re.sub(r"@media[^{]*\{", "", css)
    return [(sel.strip(), body) for sel, body in re.findall(r"([^{}]+)\{([^}]*)\}", css)]


def bodies_for(selector: str) -> list[str]:
    return [
        body for sel, body in rules(STYLE_CSS) if selector in [s.strip() for s in sel.split(",")]
    ]


@pytest.mark.parametrize("level", ["calm", "high"])
def test_tension_changes_body_image_color(level: str) -> None:
    bodies = bodies_for(f'.buddy[data-tension="{level}"] .buddy-body')
    assert any("filter:" in body for body in bodies)


def test_normal_tension_keeps_image_color_and_moves_buddy() -> None:
    assert bodies_for('.buddy[data-tension="normal"] .buddy-body') == []
    assert any("animation:" in body for body in bodies_for('.buddy[data-tension="normal"]'))


def test_calm_eyelids_follow_body_color() -> None:
    # 半目のまぶたは体と同じ filter で、体の色とそろえる
    together = [
        body
        for sel, body in rules(STYLE_CSS)
        if '.buddy[data-tension="calm"] .buddy-body' in sel
        and '.buddy[data-tension="calm"] .eyelid' in sel
    ]
    assert any("filter:" in body for body in together)


def test_high_glows_around_body_image() -> None:
    bodies = bodies_for('.buddy[data-tension="high"] .buddy-svg')
    assert any("drop-shadow" in body for body in bodies)


@pytest.mark.parametrize(("kind", "keyframe"), [("death", "effect-fade"), ("clear", "effect-jump")])
def test_effect_applies_to_element_containing_body_image(kind: str, keyframe: str) -> None:
    bodies = bodies_for(f'body[data-effect="{kind}"] .buddy-motion')
    assert any(keyframe in body for body in bodies)


def test_death_fade_makes_body_gray() -> None:
    match = re.search(r"@keyframes effect-fade \{(.*?)\n\}", STYLE_CSS, flags=re.DOTALL)
    assert match
    assert "grayscale(0.8)" in match.group(1)


# 素材のライセンスとクレジット


@pytest.mark.parametrize("path", ["assets/LICENSE", "CREDITS.md"])
def test_asset_license_and_credits(path: str) -> None:
    text = (ROOT / path).read_text(encoding="utf-8")
    assert "mendako-body.png" in text
    assert "CC BY 4.0" in text
    assert "Tsukimi-0919" in text
    assert "https://creativecommons.org/licenses/by/4.0/" in text


def test_readme_license_section_points_to_asset_license_and_credits() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    section = readme.split("## ライセンス")[1]
    assert "](assets/LICENSE)" in section
    assert "](CREDITS.md)" in section
    assert "素材の追加時に用意します" not in section
