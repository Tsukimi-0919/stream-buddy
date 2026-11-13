"""stream-buddy.exe のアイコンを作る (T-20)。

    uv run --group build python scripts/make_icon.py

Normal の表情のメンダコ (体の画像 + 目と閉じた口) を描き、次を書き出す。

- assets/icon/stream-buddy.ico      (16・24・32・48・64・128・256 px)
- assets/icon/stream-buddy-256.png  (確認用)

顔の位置・大きさ・形・色は、ページ (overlay/index.html と static/style.css) から読み取り、
Pillow で同じ形に描く。ページの顔を直したら、このスクリプトを実行し直せばアイコンも合う。
絵を変えたときだけ実行し、できたファイルをコミットする (ビルドのたびには作らない)。

小さいサイズ (16・24・32 px) では目と口がつぶれるので、そのサイズだけ目を大きく、口の線を太くする
(SMALL_SIZE_BOOST)。外部とは通信しない。
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
OVERLAY_DIR = ROOT / "src" / "stream_buddy" / "overlay"
INDEX_HTML = OVERLAY_DIR / "index.html"
STYLE_CSS = OVERLAY_DIR / "static" / "style.css"
BODY_IMAGE = OVERLAY_DIR / "static" / "img" / "mendako-body.png"
ICON_DIR = ROOT / "assets" / "icon"
ICO_FILE = ICON_DIR / "stream-buddy.ico"
PREVIEW_FILE = ICON_DIR / "stream-buddy-256.png"

SIZES = (16, 24, 32, 48, 64, 128, 256)
# 小さいサイズだけの調整: (目の半径の倍率, 口の線の太さの倍率)。ここにないサイズは (1, 1)
SMALL_SIZE_BOOST: dict[int, tuple[float, float]] = {
    16: (1.9, 2.6),
    24: (1.6, 2.0),
    32: (1.35, 1.6),
}
# 体の周りの余白 (正方形の一辺に対する割合。小さいサイズでも大きく見えるよう少なめ)
MARGIN = 0.02
# なめらかに描くため、いったん大きく描いてから縮める倍率
SUPERSAMPLE = 4
# 口の曲線を折れ線で描くときの分割数
CURVE_STEPS = 32


class IconError(Exception):
    pass


@dataclass(frozen=True)
class Face:
    """体の画像の座標 (0〜512) での顔の部品。"""

    eyes: tuple[tuple[float, float, float], ...]  # (x, y, 半径)
    mouth: tuple[tuple[float, float], tuple[float, float], tuple[float, float]]  # 2 次ベジェ
    mouth_width: float
    eye_color: str
    mouth_color: str


def _search(pattern: str, text: str, what: str) -> re.Match[str]:
    match = re.search(pattern, text, flags=re.DOTALL)
    if match is None:
        raise IconError(f"{what} が見つかりません")
    return match


def _css_value(css: str, selector: str, prop: str) -> str:
    body = _search(rf"(?:^|\n){re.escape(selector)} \{{([^}}]*)\}}", css, selector).group(1)
    return _search(rf"(?:^|\s){prop}:\s*([^;]+);", body, f"{selector} の {prop}").group(1).strip()


def read_face(html: str, css: str) -> Face:
    """ページの顔のグループ (transform と部品) と色を読み、体の画像の座標に直す。"""
    t = _search(
        r'<g class="face" transform="translate\(([-\d.]+) ([-\d.]+)\) scale\(([\d.]+)\) '
        r'translate\(([-\d.]+) ([-\d.]+)\)">',
        html,
        '顔のグループ (class="face" の transform)',
    )
    tx, ty, scale, ox, oy = (float(v) for v in t.groups())

    def to_image(x: float, y: float) -> tuple[float, float]:
        return (tx + scale * (x + ox), ty + scale * (y + oy))

    eyes = tuple(
        (*to_image(float(cx), float(cy)), float(r) * scale)
        for cx, cy, r in re.findall(
            r'<circle class="eye" cx="([-\d.]+)" cy="([-\d.]+)" r="([\d.]+)"/>', html
        )
    )
    if len(eyes) != 2:
        raise IconError(f'目 (class="eye") が 2 つではありません ({len(eyes)} 個)')
    m = _search(
        r'<path class="mouth mouth-closed" d="M([-\d.]+) ([-\d.]+) '
        r'Q([-\d.]+) ([-\d.]+) ([-\d.]+) ([-\d.]+)"/>',
        html,
        '閉じた口 (class="mouth mouth-closed")',
    )
    v = [float(x) for x in m.groups()]
    mouth = (to_image(v[0], v[1]), to_image(v[2], v[3]), to_image(v[4], v[5]))
    width = float(_css_value(css, ".mouth-closed", "stroke-width")) * scale
    return Face(
        eyes=eyes,
        mouth=mouth,
        mouth_width=width,
        eye_color=_css_value(css, ".eye", "fill"),
        mouth_color=_css_value(css, ".mouth-closed", "stroke"),
    )


def square_box(body: Image.Image) -> tuple[int, int, int, int]:
    """体の不透明な部分を囲む正方形 (少しの余白つき)。中心は体の中心。"""
    bbox = body.getchannel("A").getbbox()
    if bbox is None:
        raise IconError("体の画像がすべて透明です")
    left, top, right, bottom = bbox
    side = max(right - left, bottom - top)
    side = round(side * (1 + 2 * MARGIN))
    cx, cy = (left + right) / 2, (top + bottom) / 2
    x0, y0 = round(cx - side / 2), round(cy - side / 2)
    return (x0, y0, x0 + side, y0 + side)


def _bezier(
    p0: tuple[float, float], p1: tuple[float, float], p2: tuple[float, float]
) -> list[tuple[float, float]]:
    points = []
    for i in range(CURVE_STEPS + 1):
        t = i / CURVE_STEPS
        x = (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t**2 * p2[0]
        y = (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t**2 * p2[1]
        points.append((x, y))
    return points


def render(body: Image.Image, face: Face, size: int) -> Image.Image:
    """1 つのサイズのアイコン (RGBA、背景は透明)。"""
    eye_boost, mouth_boost = SMALL_SIZE_BOOST.get(size, (1.0, 1.0))
    k = SUPERSAMPLE
    canvas = body.resize((body.width * k, body.height * k), Image.Resampling.LANCZOS)
    draw = ImageDraw.Draw(canvas)
    for x, y, r in face.eyes:
        r *= eye_boost
        draw.ellipse((k * (x - r), k * (y - r), k * (x + r), k * (y + r)), fill=face.eye_color)
    width = face.mouth_width * mouth_boost * k
    points = [(k * x, k * y) for x, y in _bezier(*face.mouth)]
    draw.line(points, fill=face.mouth_color, width=round(width), joint="curve")
    # 線の両端を丸くする (stroke-linecap: round)
    for x, y in (points[0], points[-1]):
        draw.ellipse(
            (x - width / 2, y - width / 2, x + width / 2, y + width / 2), fill=face.mouth_color
        )
    box = tuple(k * v for v in square_box(body))
    return canvas.crop(box).resize((size, size), Image.Resampling.LANCZOS)


def make_icons() -> dict[int, Image.Image]:
    body = Image.open(BODY_IMAGE).convert("RGBA")
    face = read_face(INDEX_HTML.read_text(encoding="utf-8"), STYLE_CSS.read_text(encoding="utf-8"))
    return {size: render(body, face, size) for size in SIZES}


def main() -> int:
    try:
        icons = make_icons()
    except (IconError, OSError) as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    largest = icons[max(SIZES)]
    others = [icons[s] for s in SIZES if s != max(SIZES)]
    largest.save(ICO_FILE, format="ICO", sizes=[(s, s) for s in SIZES], append_images=others)
    largest.save(PREVIEW_FILE, format="PNG")
    print(
        f"書き出しました: {ICO_FILE.relative_to(ROOT).as_posix()} ({', '.join(map(str, SIZES))} px)"
    )
    print(f"書き出しました: {PREVIEW_FILE.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
