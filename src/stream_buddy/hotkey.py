"""ホットキー (FR-08、SR-05)。

Windows の RegisterHotKey で、設定した 2 つのキー (の組み合わせ) だけを登録して受け取る。
それ以外のキー入力は一切見ない。キーボードのフックやキーの状態を調べる API は使わない。

user32 で呼ぶのは RegisterHotKey・UnregisterHotKey・GetMessageW・PostThreadMessageW だけ。
Win32 API を呼ぶ部分は User32Api に分け、テストでは偽物に差し替える (CI ではキーを押せないため)。
"""

import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from stream_buddy.config import HotkeysConfig, parse_hotkey
from stream_buddy.state.events import EventKind

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000  # 押しっぱなしの連続入力を受け取らない
VK_F1 = 0x70  # VK_F1〜VK_F12 は連続 (0x70〜0x7B)
WM_QUIT = 0x0012
WM_HOTKEY = 0x0312
ERROR_HOTKEY_ALREADY_REGISTERED = 1409

_MODIFIER_BITS = {"Ctrl": MOD_CONTROL, "Alt": MOD_ALT, "Shift": MOD_SHIFT}
# RegisterHotKey の id (このスレッドの中で一意であればよい)
HOTKEY_IDS: dict[int, EventKind] = {1: "death", 2: "clear"}
_STOP_TIMEOUT_SECONDS = 2.0


def to_win32(text: str) -> tuple[int, int]:
    """「Ctrl+Shift+F9」を、RegisterHotKey に渡す (修飾キーのビット, 仮想キーコード) にする。"""
    spec = parse_hotkey(text)
    modifiers = MOD_NOREPEAT
    for name in spec.modifiers:
        modifiers |= _MODIFIER_BITS[name]
    return modifiers, VK_F1 + int(spec.key.removeprefix("F")) - 1


class Win32Api(Protocol):
    def register_hotkey(self, hotkey_id: int, modifiers: int, vk: int) -> int:
        """登録できたら 0、できなければ Windows のエラーコード。"""
        ...

    def unregister_hotkey(self, hotkey_id: int) -> None: ...

    def get_message(self) -> tuple[int, int] | None:
        """このスレッドのメッセージを待ち、(message, wParam) を返す。WM_QUIT やエラーなら None。"""
        ...

    def post_quit(self, thread_id: int) -> bool: ...


class User32Api:
    """本物の Win32 API (ctypes)。argtypes と restype を決め、エラーは use_last_error で取る。"""

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        self._ctypes = ctypes
        self._msg_type = wintypes.MSG
        user32 = ctypes.WinDLL("user32", use_last_error=True)

        self._register = user32.RegisterHotKey
        self._register.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        self._register.restype = wintypes.BOOL

        self._unregister = user32.UnregisterHotKey
        self._unregister.argtypes = [wintypes.HWND, ctypes.c_int]
        self._unregister.restype = wintypes.BOOL

        self._get_message = user32.GetMessageW
        self._get_message.argtypes = [
            ctypes.POINTER(wintypes.MSG),
            wintypes.HWND,
            wintypes.UINT,
            wintypes.UINT,
        ]
        self._get_message.restype = wintypes.BOOL

        self._post_thread_message = user32.PostThreadMessageW
        self._post_thread_message.argtypes = [
            wintypes.DWORD,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        self._post_thread_message.restype = wintypes.BOOL

    def register_hotkey(self, hotkey_id: int, modifiers: int, vk: int) -> int:
        # hWnd が NULL なので、WM_HOTKEY は登録したスレッドのメッセージキューに届く
        if self._register(None, hotkey_id, modifiers, vk):
            return 0
        return self._ctypes.get_last_error() or -1

    def unregister_hotkey(self, hotkey_id: int) -> None:
        self._unregister(None, hotkey_id)

    def get_message(self) -> tuple[int, int] | None:
        msg = self._msg_type()
        result = self._get_message(self._ctypes.byref(msg), None, 0, 0)
        # 0 は WM_QUIT、-1 はエラー
        if result in (0, -1):
            return None
        return int(msg.message), int(msg.wParam)

    def post_quit(self, thread_id: int) -> bool:
        return bool(self._post_thread_message(thread_id, WM_QUIT, 0, 0))


@dataclass(frozen=True)
class HotkeyFailure:
    kind: EventKind
    key: str
    error: int

    def message(self) -> str:
        if self.error == ERROR_HOTKEY_ALREADY_REGISTERED:
            reason = "ほかのアプリが使っているため登録できませんでした"
        else:
            reason = f"登録できませんでした（Windows のエラー {self.error}）"
        return f"{self.key}（{self.kind}）は{reason}。config.toml で別のキーにしてください。"


class HotkeyListener:
    """専用のスレッドでホットキーを登録し、押されたら on_hotkey(kind) を呼ぶ。

    on_hotkey はこのスレッドから呼ばれる (asyncio へは call_soon_threadsafe で渡すこと)。
    登録に失敗したキーは無効にして続ける (start の戻り値で知らせる)。
    """

    def __init__(
        self,
        config: HotkeysConfig,
        on_hotkey: Callable[[EventKind], object],
        api_factory: Callable[[], Win32Api] = User32Api,
    ) -> None:
        self._keys: Mapping[int, tuple[EventKind, str]] = {
            1: ("death", config.death),
            2: ("clear", config.clear),
        }
        self._on_hotkey = on_hotkey
        # API の準備 (DLL の読み込み) はここで行い、失敗したら起動時に例外にする
        self._api = api_factory()
        self._thread = threading.Thread(target=self._run, name="hotkeys", daemon=True)
        self._thread_id: int | None = None
        self._ready = threading.Event()
        self._stopping = threading.Event()
        self.failures: list[HotkeyFailure] = []
        self.registered: list[str] = []

    def start(self) -> list[HotkeyFailure]:
        """スレッドを始め、登録が終わるのを待つ。登録できなかったキーを返す。"""
        self._thread.start()
        self._ready.wait(_STOP_TIMEOUT_SECONDS)
        return list(self.failures)

    def stop(self) -> None:
        """スレッドに WM_QUIT を送って止める。何度呼んでもよい。"""
        self._stopping.set()
        deadline = time.monotonic() + _STOP_TIMEOUT_SECONDS
        # スレッドのメッセージキューができる前は送れないので、届くまで少し待って送り直す
        while self._thread.is_alive() and time.monotonic() < deadline:
            thread_id = self._thread_id
            if thread_id is not None and self._api.post_quit(thread_id):
                break
            time.sleep(0.01)
        if self._thread.is_alive():
            self._thread.join(max(0.0, deadline - time.monotonic()))

    @property
    def running(self) -> bool:
        return self._thread.is_alive()

    def _run(self) -> None:
        # RegisterHotKey(NULL, ...) は呼んだスレッドに結びつくので、
        # 登録も受け取りもこのスレッドで行う
        self._thread_id = threading.get_native_id()
        api = self._api
        registered: list[int] = []
        try:
            for hotkey_id, (kind, key) in self._keys.items():
                modifiers, vk = to_win32(key)
                error = api.register_hotkey(hotkey_id, modifiers, vk)
                if error == 0:
                    registered.append(hotkey_id)
                    self.registered.append(key)
                else:
                    self.failures.append(HotkeyFailure(kind, key, error))
            self._ready.set()
            while not self._stopping.is_set():
                message = api.get_message()
                if message is None:
                    break
                msg, wparam = message
                if msg == WM_HOTKEY and wparam in registered:
                    self._on_hotkey(self._keys[wparam][0])
        finally:
            # 例外のときも、登録したキーは必ず外す
            for hotkey_id in registered:
                api.unregister_hotkey(hotkey_id)
            self._ready.set()
