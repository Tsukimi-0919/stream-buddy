"""stream-buddy を PyInstaller で exe にする (T-07 の試作)。

ビルドの設定はすべてこのファイルにまとめる。Nuitka に切り替えるときは、ここだけを直す。

    uv run --group build python scripts/build_exe.py                  (onedir)
    uv run --group build python scripts/build_exe.py --mode onefile

配布には onedir を使う (ADR 0004)。

出力先
- onedir:  dist/stream-buddy/stream-buddy.exe (とその隣の _internal/)
- onefile: dist/stream-buddy-onefile/stream-buddy.exe
どちらも exe と同じフォルダに config.example.toml を置く。手順は docs/build.md を参照。

ビルドの情報 (git のコミットと変更の有無、日付) を exe に同梱し、--version に出す。
git が使えないときはビルドしない。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / "src"
PACKAGE_DIR = SRC_DIR / "stream_buddy"
ENTRY_SCRIPT = PACKAGE_DIR / "__main__.py"
OVERLAY_DIR = PACKAGE_DIR / "overlay"
DATA_DIR = PACKAGE_DIR / "data"
CONFIG_EXAMPLE = ROOT / "config.example.toml"
DIST_ROOT = ROOT / "dist"
BUILD_ROOT = ROOT / "build"
# ビルドの情報 (コミット・変更の有無・日付)。コミットに混ざらないよう src/ ではなく build/ に書き、
# exe の中の stream_buddy/data/build_info.json として同梱する (build_info.py が読む)
BUILD_INFO_FILE = BUILD_ROOT / "build_info.json"

APP_NAME = "stream-buddy"
EXE_NAME = f"{APP_NAME}.exe"
# exe の中で server.py が Path(__file__).parent / "overlay" で見つけられる場所に置く
OVERLAY_DEST = "stream_buddy/overlay"
# 既定のセリフ集など。lines.py が importlib.resources で stream_buddy/data から読む
DATA_DEST = "stream_buddy/data"
# sounddevice は _sounddevice_data/portaudio-binaries/ から DLL を読み込む
PORTAUDIO_DEST = "_sounddevice_data/portaudio-binaries"
PORTAUDIO_DLL = "libportaudio64bit.dll"
# vosk は vosk/ の DLL (libvosk.dll など) を自分のフォルダから読み込むので、そこに置く。
# 音声認識モデルは同梱しない (利用者が公式サイトから取得し、起動時にハッシュで確かめる)
VOSK_PACKAGE = "vosk"
# 入っていても exe に含めない (音声認識のスパイクと、テスト・型チェックの依存)。
# dev グループの mypy は、pydantic の mypy プラグイン経由で集められてしまうため明示する
EXCLUDED_MODULES = [
    "faster_whisper",
    "ctranslate2",
    "onnxruntime",
    "pytest",
    "_pytest",
    "mypy",
    "ast_serialize",
]
VERSION_TIMEOUT_SECONDS = 60
GIT_TIMEOUT_SECONDS = 30
# PyInstaller の --add-data の区切り (6.x はどの OS でも ":" を受け付ける)
_DATA_SEP = ":"


class BuildError(Exception):
    pass


# git の引数を受け取り、標準出力を返す。失敗したら BuildError
type GitRunner = Callable[[list[str]], str]


def run_git(args: list[str]) -> str:
    git = shutil.which("git")
    if git is None:
        raise BuildError("git が見つかりません (どのコードから作ったかわからない exe は作りません)")
    try:
        # 引数はリストで渡し、シェルを通さない
        result = subprocess.run(  # noqa: S603
            [git, *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise BuildError(f"git {' '.join(args)} を実行できません: {e}") from e
    if result.returncode != 0:
        raise BuildError(
            f"git {' '.join(args)} が失敗しました (終了コード {result.returncode})\n"
            f"{result.stderr.strip()}"
        )
    return result.stdout


def make_build_info(git: GitRunner, today: date) -> dict[str, object]:
    """ビルドの情報を作る。日付はビルドした PC のローカルの日付。"""
    commit = git(["rev-parse", "--short", "HEAD"]).strip()
    if not commit:
        raise BuildError("git rev-parse --short HEAD の結果が空です")
    dirty = bool(git(["status", "--porcelain"]).strip())
    return {"commit": commit, "dirty": dirty, "date": today.isoformat()}


def write_build_info(info: dict[str, object]) -> Path:
    BUILD_INFO_FILE.parent.mkdir(parents=True, exist_ok=True)
    BUILD_INFO_FILE.write_text(json.dumps(info) + "\n", encoding="utf-8")
    return BUILD_INFO_FILE


def output_dir(mode: str) -> Path:
    """exe を置くフォルダ。"""
    if mode == "onedir":
        return DIST_ROOT / APP_NAME
    return DIST_ROOT / f"{APP_NAME}-onefile"


def work_dir(mode: str) -> Path:
    """PyInstaller の作業フォルダ (.spec もここに作る)。"""
    return BUILD_ROOT / f"{APP_NAME}-{mode}"


def remove_previous(path: Path) -> None:
    """前回の出力を消す。dist/ と build/ の中に収まっているものだけを消す。"""
    resolved = path.resolve()
    if not any(resolved.is_relative_to(root.resolve()) for root in (DIST_ROOT, BUILD_ROOT)):
        raise BuildError(f"dist/ と build/ の外は消しません: {path}")
    if resolved in (DIST_ROOT.resolve(), BUILD_ROOT.resolve()):
        raise BuildError(f"dist/ と build/ そのものは消しません: {path}")
    if resolved.is_dir():
        shutil.rmtree(resolved)
    elif resolved.exists():
        resolved.unlink()


def portaudio_dll() -> Path:
    import _sounddevice_data  # type: ignore[import-untyped]

    dll = Path(next(iter(_sounddevice_data.__path__))) / "portaudio-binaries" / PORTAUDIO_DLL
    if not dll.is_file():
        raise BuildError(f"PortAudio の DLL が見つかりません: {dll}")
    return dll


def pyinstaller_args(mode: str) -> list[str]:
    dist = output_dir(mode)
    work = work_dir(mode)
    # onedir は distpath の下に APP_NAME のフォルダを作るため、1 つ上を渡す
    distpath = dist.parent if mode == "onedir" else dist
    args = [
        str(ENTRY_SCRIPT),
        "--name",
        APP_NAME,
        f"--{mode}",
        "--console",  # OBS の URL を表示するため、コンソールを出す
        "--noupx",  # UPX の圧縮は Defender の誤検知が増えやすいため使わない
        "--noconfirm",
        "--clean",
        "--distpath",
        str(distpath),
        "--workpath",
        str(work),
        "--specpath",
        str(work),
        "--paths",
        str(SRC_DIR),
        "--add-data",
        f"{OVERLAY_DIR}{_DATA_SEP}{OVERLAY_DEST}",
        "--add-data",
        f"{DATA_DIR}{_DATA_SEP}{DATA_DEST}",
        "--add-data",
        f"{BUILD_INFO_FILE}{_DATA_SEP}{DATA_DEST}",
        "--add-binary",
        f"{portaudio_dll()}{_DATA_SEP}{PORTAUDIO_DEST}",
        "--collect-binaries",
        VOSK_PACKAGE,
    ]
    for module in EXCLUDED_MODULES:
        args += ["--exclude-module", module]
    return args


def run_pyinstaller(mode: str) -> None:
    command = [sys.executable, "-m", "PyInstaller", *pyinstaller_args(mode)]
    # 引数はリストで渡し、シェルを通さない
    result = subprocess.run(command, cwd=ROOT, check=False)  # noqa: S603
    if result.returncode != 0:
        raise BuildError(f"PyInstaller が失敗しました (終了コード {result.returncode})")


def folder_size(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def expected_version(info: dict[str, object]) -> str:
    """exe の --version に出るはずの表示 (例: stream-buddy 0.1.0 (b12307a, 2026-11-05))。"""
    sys.path.insert(0, str(SRC_DIR))
    from stream_buddy import __version__
    from stream_buddy.build_info import format_label

    label = format_label(info)
    if label is None:
        raise BuildError(f"ビルドの情報の形が正しくありません: {info!r}")
    return f"stream-buddy {__version__} ({label})"


def check_version(exe: Path, info: dict[str, object]) -> str:
    """exe で --version を実行し、出力を返す。期待と違えば BuildError。"""
    expected = expected_version(info)
    try:
        result = subprocess.run(  # noqa: S603
            [str(exe), "--version"],
            capture_output=True,
            text=True,
            timeout=VERSION_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise BuildError(f"--version が {VERSION_TIMEOUT_SECONDS} 秒で終わりませんでした") from e
    output = result.stdout.strip()
    if result.returncode != 0 or output != expected:
        raise BuildError(
            f"--version の結果が違います (終了コード {result.returncode}、"
            f"出力 {output!r}、期待 {expected!r})\n{result.stderr}"
        )
    return output


def build(mode: str) -> None:
    dist = output_dir(mode)
    for path in (dist, work_dir(mode)):
        remove_previous(path)
    # git が使えなければ、ここで止める (PyInstaller を動かす前)
    info = make_build_info(run_git, date.today())
    write_build_info(info)

    start = time.perf_counter()
    run_pyinstaller(mode)
    elapsed = time.perf_counter() - start

    exe = dist / EXE_NAME
    if not exe.is_file():
        raise BuildError(f"exe ができていません: {exe}")
    shutil.copy2(CONFIG_EXAMPLE, dist / CONFIG_EXAMPLE.name)

    version = check_version(exe, info)
    size = folder_size(dist) if mode == "onedir" else exe.stat().st_size
    size_label = "フォルダ全体の合計サイズ" if mode == "onedir" else "exe のサイズ"

    print()
    print(f"ビルドが終わりました ({mode}、{elapsed:.0f} 秒)")
    print(f"  出力の場所: {dist.relative_to(ROOT).as_posix()}/")
    print(f"  {size_label}: {size / 1_000_000:.1f} MB ({size:,} バイト)")
    print(f"  {EXE_NAME} の SHA-256: {sha256(exe)}")
    print(f"  --version: {version}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="stream-buddy を PyInstaller で exe にする")
    parser.add_argument(
        "--mode",
        choices=["onedir", "onefile"],
        default="onedir",
        help="フォルダか、1 ファイルか (既定: onedir。配布に使う形、ADR 0004)",
    )
    args = parser.parse_args(argv)
    try:
        build(args.mode)
    except BuildError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
