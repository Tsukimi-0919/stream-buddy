"""ホットキーのテスト。CI ではキーを押せないので、Win32 API は偽物に差し替える。"""

import ast
import asyncio
import queue
import re
import threading
from pathlib import Path

import pytest

import stream_buddy.__main__ as main_module
from stream_buddy import hotkey
from stream_buddy.__main__ import main
from stream_buddy.config import ConfigError, HotkeysConfig, load_config, parse_hotkey
from stream_buddy.hotkey import (
    ERROR_HOTKEY_ALREADY_REGISTERED,
    MOD_ALT,
    MOD_CONTROL,
    MOD_NOREPEAT,
    MOD_SHIFT,
    WM_HOTKEY,
    WM_QUIT,
    HotkeyListener,
    to_win32,
)

SRC = Path(hotkey.__file__).parent
VK_F9 = 0x78

# 設定


def write_config(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(text, encoding="utf-8")
    return path


def config_error(tmp_path: Path, text: str) -> str:
    with pytest.raises(ConfigError) as exc:
        load_config(write_config(tmp_path, text))
    return str(exc.value)


def test_default_hotkeys() -> None:
    assert HotkeysConfig() == HotkeysConfig(death="F9", clear="F10")


@pytest.mark.parametrize(
    ("given", "normalized"),
    [
        ("F9", "F9"),
        ("F12", "F12"),
        ("f1", "F1"),
        ("Ctrl+Shift+F9", "Ctrl+Shift+F9"),
        ("shift+ctrl+f9", "Ctrl+Shift+F9"),  # 順番と大文字・小文字は問わない
        ("ALT+ctrl+SHIFT+F5", "Ctrl+Alt+Shift+F5"),
        (" Ctrl + F9 ", "Ctrl+F9"),
    ],
)
def test_valid_hotkeys(tmp_path: Path, given: str, normalized: str) -> None:
    config = load_config(write_config(tmp_path, f'[hotkeys]\ndeath = "{given}"\n'))
    assert config.hotkeys.death == normalized


@pytest.mark.parametrize(
    ("given", "reason"),
    [
        ("F13", "F1〜F12"),
        ("F0", "F1〜F12"),
        ("A", "F1〜F12"),
        ("Enter", "F1〜F12"),
        ("Ctrl+1", "F1〜F12"),
        ("Win+F9", "Win キーなどは使えません"),
        ("Ctrl+Win+F9", "Win キーなどは使えません"),
        ("Ctrl+Ctrl+F9", "同じ修飾キー（Ctrl）が重複しています"),
        ("ctrl+Ctrl+F9", "同じ修飾キー（Ctrl）が重複しています"),
        ("Ctrl+", "F1〜F12"),
        ("", "F1〜F12"),
        ("F9+Ctrl", "Win キーなどは使えません"),
    ],
)
def test_invalid_hotkeys(tmp_path: Path, given: str, reason: str) -> None:
    message = config_error(tmp_path, f'[hotkeys]\nclear = "{given}"\n')
    assert "[hotkeys] clear は" in message
    assert reason in message


def test_same_hotkeys_including_modifiers_is_error(tmp_path: Path) -> None:
    message = config_error(tmp_path, '[hotkeys]\ndeath = "ctrl+F9"\nclear = "Ctrl+f9"\n')
    assert "death と clear に同じキーは指定できません（指定値: Ctrl+F9）" in message


def test_different_modifiers_are_different_keys(tmp_path: Path) -> None:
    config = load_config(write_config(tmp_path, '[hotkeys]\ndeath = "Ctrl+F9"\nclear = "F9"\n'))
    assert (config.hotkeys.death, config.hotkeys.clear) == ("Ctrl+F9", "F9")


# 変換


@pytest.mark.parametrize(
    ("text", "modifiers", "vk"),
    [
        ("F1", MOD_NOREPEAT, 0x70),
        ("F9", MOD_NOREPEAT, 0x78),
        ("F12", MOD_NOREPEAT, 0x7B),
        ("Ctrl+F9", MOD_NOREPEAT | MOD_CONTROL, VK_F9),
        ("Alt+F9", MOD_NOREPEAT | MOD_ALT, VK_F9),
        ("Shift+F9", MOD_NOREPEAT | MOD_SHIFT, VK_F9),
        ("Ctrl+Alt+Shift+F9", MOD_NOREPEAT | MOD_CONTROL | MOD_ALT | MOD_SHIFT, VK_F9),
    ],
)
def test_to_win32(text: str, modifiers: int, vk: int) -> None:
    assert to_win32(text) == (modifiers, vk)


def test_win32_constants() -> None:
    # Windows の定義と同じ値
    assert (MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_NOREPEAT) == (0x1, 0x2, 0x4, 0x4000)
    assert (WM_QUIT, WM_HOTKEY) == (0x12, 0x312)
    assert str(parse_hotkey("f9")) == "F9"


# 偽の Win32 API


class FakeApi:
    """偽の Win32 API。メッセージキューを持ち、send でキーが押されたことにする。"""

    def __init__(self, fail: dict[int, int] | None = None, raise_in_loop: bool = False) -> None:
        self.fail = fail or {}
        self.raise_in_loop = raise_in_loop
        self.registered: dict[int, tuple[int, int]] = {}
        self.register_calls: list[int] = []
        self.unregistered: list[int] = []
        self.posted: list[tuple[int, int]] = []
        self.messages: queue.Queue[tuple[int, int]] = queue.Queue()
        self.thread_id: int | None = None
        self.waiting = threading.Event()

    def register_hotkey(self, hotkey_id: int, modifiers: int, vk: int) -> int:
        self.thread_id = threading.get_native_id()
        self.register_calls.append(hotkey_id)
        if hotkey_id in self.fail:
            return self.fail[hotkey_id]
        self.registered[hotkey_id] = (modifiers, vk)
        return 0

    def unregister_hotkey(self, hotkey_id: int) -> None:
        self.unregistered.append(hotkey_id)

    def get_message(self) -> tuple[int, int] | None:
        self.waiting.set()
        if self.raise_in_loop:
            raise RuntimeError("壊れた")
        message = self.messages.get(timeout=5)
        return None if message[0] == WM_QUIT else message

    def post_quit(self, thread_id: int) -> bool:
        self.posted.append((thread_id, WM_QUIT))
        self.messages.put((WM_QUIT, 0))
        return True

    def send(self, hotkey_id: int) -> None:
        self.messages.put((WM_HOTKEY, hotkey_id))


def listener_with(
    api: FakeApi, config: HotkeysConfig | None = None
) -> tuple[HotkeyListener, "queue.Queue[str]"]:
    found: queue.Queue[str] = queue.Queue()
    listener = HotkeyListener(config or HotkeysConfig(), found.put, lambda: api)
    return listener, found


def test_registers_both_keys_and_unregisters_on_stop() -> None:
    api = FakeApi()
    listener, _ = listener_with(api, HotkeysConfig(death="Ctrl+Shift+F9", clear="F10"))
    assert listener.start() == []
    assert api.registered == {
        1: (MOD_NOREPEAT | MOD_CONTROL | MOD_SHIFT, VK_F9),
        2: (MOD_NOREPEAT, 0x79),
    }
    assert listener.registered == ["Ctrl+Shift+F9", "F10"]
    # 登録と受け取りは、専用のスレッドで行う
    assert api.thread_id != threading.get_native_id()
    listener.stop()
    assert sorted(api.unregistered) == [1, 2]
    assert not listener.running


def test_hotkey_message_is_mapped_to_kind() -> None:
    api = FakeApi()
    listener, found = listener_with(api)
    listener.start()
    api.send(2)
    api.send(1)
    api.send(99)  # 登録していない id は無視
    assert found.get(timeout=5) == "clear"
    assert found.get(timeout=5) == "death"
    listener.stop()
    assert found.empty()


def test_other_messages_are_ignored() -> None:
    api = FakeApi()
    listener, found = listener_with(api)
    listener.start()
    api.messages.put((0x0100, 1))  # WM_KEYDOWN など、ホットキー以外のメッセージ
    api.send(1)
    assert found.get(timeout=5) == "death"
    listener.stop()
    assert found.empty()


def test_stop_posts_quit_to_the_hotkey_thread() -> None:
    api = FakeApi()
    listener, _ = listener_with(api)
    listener.start()
    assert api.waiting.wait(5)
    listener.stop()
    assert api.posted == [(api.thread_id, WM_QUIT)]
    assert not listener.running
    listener.stop()  # 何度呼んでもよい


def test_unregisters_even_when_loop_raises() -> None:
    api = FakeApi(raise_in_loop=True)
    listener, _ = listener_with(api)
    errors: list[BaseException] = []
    threading.excepthook, original = (
        (lambda args: errors.append(args.exc_value)),
        threading.excepthook,
    )
    try:
        listener.start()
        listener.stop()
    finally:
        threading.excepthook = original
    assert sorted(api.unregistered) == [1, 2]
    assert isinstance(errors[0], RuntimeError)


def test_failed_key_is_disabled_and_reported() -> None:
    api = FakeApi(fail={1: ERROR_HOTKEY_ALREADY_REGISTERED})
    listener, found = listener_with(api)
    failures = listener.start()
    assert [(f.kind, f.key) for f in failures] == [("death", "F9")]
    assert failures[0].message() == (
        "F9（death）はほかのアプリが使っているため登録できませんでした。"
        "config.toml で別のキーにしてください。"
    )
    assert listener.registered == ["F10"]
    # もう片方は動く
    api.send(2)
    assert found.get(timeout=5) == "clear"
    listener.stop()
    # 登録できなかったキーは外さない
    assert api.unregistered == [2]


def test_other_errors_show_code() -> None:
    api = FakeApi(fail={2: 5})
    listener, _ = listener_with(api)
    failures = listener.start()
    listener.stop()
    assert "（Windows のエラー 5）" in failures[0].message()


# 確認用のオプション


def test_test_hotkeys_prints_only_kind(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    api = FakeApi()
    printed: list[str] = []

    def fake_print(*args: object, **kwargs: object) -> None:
        printed.append(" ".join(str(a) for a in args))
        if args and str(args[0]).startswith("ホットキー（"):
            api.send(1)
        if args == ("death",):
            raise KeyboardInterrupt  # Ctrl+C の代わり

    monkeypatch.setattr(main_module, "print", fake_print, raising=False)
    monkeypatch.setattr(hotkey, "User32Api", lambda: api)
    real_listener = hotkey.HotkeyListener
    monkeypatch.setattr(
        hotkey,
        "HotkeyListener",
        lambda config, on_hotkey: real_listener(config, on_hotkey, lambda: api),
    )
    assert main(["--test-hotkeys", "--config", str(tmp_path / "none.toml")]) == 0
    assert "ホットキー（F9、F10）を待っています。Ctrl+C で終了します。" in printed
    assert "death" in printed
    assert sorted(api.unregistered) == [1, 2]


def test_test_hotkeys_with_no_registered_key_exits_2(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    api = FakeApi(fail={1: ERROR_HOTKEY_ALREADY_REGISTERED, 2: ERROR_HOTKEY_ALREADY_REGISTERED})
    real_listener = hotkey.HotkeyListener
    monkeypatch.setattr(
        hotkey,
        "HotkeyListener",
        lambda config, on_hotkey: real_listener(config, on_hotkey, lambda: api),
    )
    assert main(["--test-hotkeys", "--config", str(tmp_path / "none.toml")]) == 2
    err = capsys.readouterr().err
    assert "F9（death）はほかのアプリが使っている" in err
    assert "F10（clear）はほかのアプリが使っている" in err


def test_demo_does_not_register_hotkeys(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def fail(*_: object, **__: object) -> None:
        raise AssertionError("ホットキーを登録しない")

    monkeypatch.setattr(hotkey, "HotkeyListener", fail)
    monkeypatch.setattr(main_module.server, "serve", lambda *a, **kw: None)
    monkeypatch.chdir(tmp_path)
    assert main(["--demo"]) == 0


def test_asyncio_receives_hotkey_via_call_soon_threadsafe() -> None:
    api = FakeApi()

    async def run() -> str:
        loop = asyncio.get_running_loop()
        found: asyncio.Queue[str] = asyncio.Queue()
        listener = HotkeyListener(
            HotkeysConfig(),
            lambda kind: loop.call_soon_threadsafe(found.put_nowait, kind),
            lambda: api,
        )
        listener.start()
        try:
            api.send(1)
            return await asyncio.wait_for(found.get(), 5)
        finally:
            listener.stop()

    assert asyncio.run(run()) == "death"


# SR-05: キーロガーと疑われるものを使わない (文字列・構文の検査)

FORBIDDEN_NAMES = [
    "SetWindowsHookEx",
    "GetAsyncKeyState",
    "GetKeyState",
    "GetKeyboardState",
    "RegisterRawInputDevices",
]
KEYBOARD_LIBRARIES = ["keyboard", "pynput", "pywin32", "win32api", "win32con", "win32gui", "pyHook"]


@pytest.mark.parametrize("path", sorted(SRC.rglob("*.py")), ids=lambda p: p.name)
def test_no_keyboard_hooks_or_key_state(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    for name in FORBIDDEN_NAMES:
        assert name not in text, f"{path.name} に {name} がある"
    tree = ast.parse(text)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not imported & set(KEYBOARD_LIBRARIES), (
        f"{path.name} がキーボードのライブラリを使っている"
    )


def test_hotkey_uses_only_allowed_user32_functions() -> None:
    text = (SRC / "hotkey.py").read_text(encoding="utf-8")
    used = set(re.findall(r"user32\.(\w+)", text))
    assert used == {"RegisterHotKey", "UnregisterHotKey", "GetMessageW", "PostThreadMessageW"}
    # user32 以外の DLL も読み込まない
    assert re.findall(r'WinDLL\("(\w+)"', text) == ["user32"]
