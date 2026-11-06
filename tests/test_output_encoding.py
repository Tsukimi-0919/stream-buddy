"""日本語を表示できない出力先でも、出力で止まらないこと (T-18)。"""

import importlib.util
import io
import sys
from pathlib import Path
from types import ModuleType

import pytest

from stream_buddy.__main__ import main, use_replace_errors

SCRIPT = Path(__file__).parent.parent / "scripts" / "build_exe.py"
MESSAGE = "設定ファイルを読めません"


def cp1252_stream() -> tuple[io.BytesIO, io.TextIOWrapper]:
    raw = io.BytesIO()
    return raw, io.TextIOWrapper(raw, encoding="cp1252")


def load_build_exe() -> ModuleType:
    spec = importlib.util.spec_from_file_location("build_exe_output", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cp1252_stream_fails_without_setting() -> None:
    # 前提の確認：何もしないと UnicodeEncodeError で止まる
    _, stream = cp1252_stream()
    with pytest.raises(UnicodeEncodeError):
        print(MESSAGE, file=stream, flush=True)


def test_use_replace_errors_does_not_raise() -> None:
    raw, stream = cp1252_stream()
    use_replace_errors(stream)
    print(f"stream-buddy {MESSAGE}", file=stream, flush=True)
    text = raw.getvalue().decode("cp1252")
    assert text.startswith("stream-buddy ")
    assert "?" in text


def test_use_replace_errors_keeps_encoding() -> None:
    # 日本語を表示できる出力先では、今までどおり日本語で出す
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="utf-8")
    use_replace_errors(stream)
    print(MESSAGE, file=stream, flush=True)
    assert raw.getvalue().decode("utf-8").strip() == MESSAGE


def test_use_replace_errors_ignores_non_text_stream() -> None:
    # exe をウィンドウなしで動かすと sys.stdout が None になることがある
    use_replace_errors(None)
    use_replace_errors(io.StringIO())


def test_main_error_message_to_cp1252_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "config.toml"
    config.write_text("これは TOML ではない = = =\n", encoding="utf-8")
    raw, stream = cp1252_stream()
    monkeypatch.setattr(sys, "stderr", stream)
    assert main(["--config", str(config)]) == 2
    stream.flush()
    assert raw.getvalue()


def test_build_exe_error_message_to_cp1252_stderr(monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_build_exe()

    def fail(mode: str) -> None:
        raise module.BuildError(f"{MESSAGE} ({mode})")

    monkeypatch.setattr(module, "build", fail)
    raw, stream = cp1252_stream()
    monkeypatch.setattr(sys, "stderr", stream)
    assert module.main([]) == 1
    stream.flush()
    assert "(onedir)" in raw.getvalue().decode("cp1252")
