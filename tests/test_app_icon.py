"""exe のアイコン (T-20)。ICO と PNG は標準ライブラリだけで読む。"""

import ast
import struct
import zlib
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
ICO_FILE = ROOT / "assets" / "icon" / "stream-buddy.ico"
PREVIEW_FILE = ROOT / "assets" / "icon" / "stream-buddy-256.png"
MAKE_ICON = ROOT / "scripts" / "make_icon.py"
SIZES = (16, 24, 32, 48, 64, 128, 256)
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
NETWORK_MODULES = {
    "urllib",
    "urllib3",
    "http",
    "socket",
    "ssl",
    "requests",
    "httpx",
    "aiohttp",
    "ftplib",
    "smtplib",
    "webbrowser",
    "xmlrpc",
}


def ico_frames(data: bytes) -> dict[int, bytes]:
    """ICO の各画像 (一辺の大きさ → 画像のデータ)。"""
    reserved, kind, count = struct.unpack("<HHH", data[:6])
    assert (reserved, kind) == (0, 1)  # 1 = アイコン
    frames: dict[int, bytes] = {}
    for i in range(count):
        entry = data[6 + 16 * i : 6 + 16 * (i + 1)]
        width, height = entry[0] or 256, entry[1] or 256
        size, offset = struct.unpack("<II", entry[8:16])
        assert width == height
        frames[width] = data[offset : offset + size]
    return frames


def _png_rows(png: bytes) -> tuple[int, int, list[bytearray]]:
    """8 ビット RGBA の PNG を、行ごとの画素 (RGBA の並び) に戻す。"""
    assert png[:8] == PNG_SIGNATURE
    pos, idat = 8, b""
    width = height = 0
    while pos < len(png):
        (length,) = struct.unpack(">I", png[pos : pos + 4])
        kind, body = png[pos + 4 : pos + 8], png[pos + 8 : pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR":
            width, height, depth, color, _, _, interlace = struct.unpack(">IIBBBBB", body)
            assert (depth, color, interlace) == (8, 6, 0)
        elif kind == b"IDAT":
            idat += body
    raw = zlib.decompress(idat)
    stride = width * 4
    rows: list[bytearray] = []
    prev = bytearray(stride)
    for y in range(height):
        start = y * (stride + 1)
        kind_, row = raw[start], bytearray(raw[start + 1 : start + 1 + stride])
        for x in range(stride):
            a = row[x - 4] if x >= 4 else 0
            b = prev[x]
            c = prev[x - 4] if x >= 4 else 0
            if kind_ == 1:
                row[x] = (row[x] + a) & 0xFF
            elif kind_ == 2:
                row[x] = (row[x] + b) & 0xFF
            elif kind_ == 3:
                row[x] = (row[x] + (a + b) // 2) & 0xFF
            elif kind_ == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if pa <= pb and pa <= pc else b if pb <= pc else c
                row[x] = (row[x] + pred) & 0xFF
        rows.append(row)
        prev = row
    return width, height, rows


def frame_alphas(frame: bytes) -> tuple[int, int, list[int]]:
    """ICO の 1 枚の画像の (幅, 高さ, アルファの一覧)。PNG と 32 ビットの BMP に対応。"""
    if frame.startswith(PNG_SIGNATURE):
        width, height, rows = _png_rows(frame)
        return width, height, [a for row in rows for a in row[3::4]]
    header_size, width, double_height, _, bpp = struct.unpack("<IiiHH", frame[:16])
    assert bpp == 32
    pixels = frame[header_size : header_size + width * width * 4]
    return width, double_height // 2, list(pixels[3::4])


def test_ico_has_all_sizes() -> None:
    frames = ico_frames(ICO_FILE.read_bytes())
    assert sorted(frames) == list(SIZES)


@pytest.mark.parametrize("size", SIZES)
def test_each_size_has_transparent_and_opaque_parts(size: int) -> None:
    frame = ico_frames(ICO_FILE.read_bytes())[size]
    width, height, alphas = frame_alphas(frame)
    assert (width, height) == (size, size)
    assert 0 in alphas  # 背景は透明
    assert 255 in alphas  # メンダコは不透明


def test_preview_png_is_256() -> None:
    width, height, rows = _png_rows(PREVIEW_FILE.read_bytes())
    assert (width, height) == (256, 256)
    assert rows[0][3] == 0  # 左上の角は透明


def test_make_icon_does_not_import_network_modules() -> None:
    tree = ast.parse(MAKE_ICON.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported
    assert not imported & NETWORK_MODULES
    assert "__import__" not in MAKE_ICON.read_text(encoding="utf-8")


def test_credits_has_icon() -> None:
    credits = (ROOT / "CREDITS.md").read_text(encoding="utf-8")
    line = next(line for line in credits.splitlines() if "assets/icon/stream-buddy.ico" in line)
    assert "mendako-body.png" in line
    assert "CC BY 4.0" in line
