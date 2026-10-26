"""stream-buddy のコマンドラインエントリポイント。"""

import argparse
import asyncio
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from stream_buddy import __version__, audio, hotkey, keywords, server
from stream_buddy.config import Config, ConfigError, load_config
from stream_buddy.state.events import EventKind
from stream_buddy.token_store import TokenStoreError, default_token_dir, load_or_create_token


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="stream-buddy")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config.toml"),
        help="設定ファイルのパス (省略時はカレントフォルダの config.toml。なければ既定値)",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="見え方の確認用に、決まった流れのメッセージを繰り返し送る",
    )
    parser.add_argument(
        "--reset-token",
        action="store_true",
        help="URL のトークンを作り直す (URL が漏れたときに使う。OBS の URL の設定し直しが必要)",
    )
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="入力デバイス (マイク) の番号と名前を表示して終了する",
    )
    parser.add_argument(
        "--check-model",
        action="store_true",
        help="音声認識モデルが公式に配布されたものと一致するかを確かめて終了する",
    )
    parser.add_argument(
        "--test-keywords",
        action="store_true",
        help="サーバーを起動せず、聞き取ったキーワードの種類 (death / clear) だけを表示する",
    )
    parser.add_argument(
        "--test-hotkeys",
        action="store_true",
        help="ホットキーだけを登録し、押されたキーの種類 (death / clear) を表示する",
    )
    args = parser.parse_args(argv)

    if args.list_devices:
        try:
            print(audio.format_devices(audio.default_backend().input_devices()))
        except audio.AudioError as e:
            print(e, file=sys.stderr)
            return 2
        return 0

    try:
        config = load_config(args.config)
    except ConfigError as e:
        print(e, file=sys.stderr)
        return 2

    if args.check_model:
        return _check_model(config)

    # ホットキーの確認では、マイクも音声認識もサーバーも使わない
    if args.test_hotkeys:
        return _test_hotkeys(config)

    # デモのときはマイクも音声認識もホットキーも使わない
    # (ホットキーを Brain につなぐのは T-12。それまでは --test-hotkeys のときだけ登録する)
    if args.demo:
        return _run(args, config, None)

    try:
        setup = keywords.prepare_keywords(config.keywords)
    except ConfigError as e:
        print(e, file=sys.stderr)
        return 2
    if setup is None and config.keywords.enabled:
        print(keywords.MISSING_MODEL_MESSAGE)
    if args.test_keywords and setup is None:
        print("キーワード検知が無効なため、--test-keywords は使えません。", file=sys.stderr)
        return 2

    try:
        backend = audio.default_backend()
        device = audio.select_device(config.audio.device, backend.input_devices())
        microphone = audio.Microphone(backend, device)
    except audio.AudioError as e:
        print(e, file=sys.stderr)
        return 2

    try:
        if args.test_keywords and setup is not None:
            return _test_keywords(microphone, setup)
        # キーワード検知を Brain につなぐのは T-12。ここではモデルの確認と準備までを行う
        return _run(args, config, microphone)
    finally:
        # Ctrl+C やエラーで終わっても、ストリームを確実に閉じる
        microphone.close()


def _check_model(config: Config) -> int:
    model_dir = keywords.resolve_model_dir(config.keywords.model_dir)
    if not model_dir.is_dir():
        print(keywords.MISSING_MODEL_MESSAGE, file=sys.stderr)
        return 2
    try:
        count = keywords.verify_model(model_dir)
    except ConfigError as e:
        print(e, file=sys.stderr)
        return 2
    print(f"音声認識モデルは公式に配布されたものと一致しました（{count} ファイル）。")
    return 0


def _test_keywords(microphone: audio.Microphone, setup: keywords.KeywordSetup) -> int:
    """聞き取ったキーワードの種類だけを表示する。認識した文字列は出さない。"""

    async def listen() -> None:
        loop = asyncio.get_running_loop()
        found: asyncio.Queue[EventKind] = asyncio.Queue()
        blocks = audio.BlockQueue()
        listener = keywords.KeywordListener(
            setup.spotter(),
            blocks,
            # 認識用のスレッドから呼ばれる。ループへは種類だけを渡す
            lambda kind: loop.call_soon_threadsafe(found.put_nowait, kind),
        )
        microphone.set_sample_sink(blocks.offer)
        microphone.start(lambda _level: None)
        listener.start()
        try:
            print("キーワードを聞いています。Ctrl+C で終了します。", flush=True)
            while True:
                print(await found.get(), flush=True)
        finally:
            microphone.set_sample_sink(None)
            listener.stop()

    try:
        asyncio.run(listen())
    except KeyboardInterrupt:
        print("終了しました。")
    return 0


def _test_hotkeys(config: Config) -> int:
    """ホットキーだけを登録し、押されたキーの種類を表示する。"""

    async def listen() -> bool:
        loop = asyncio.get_running_loop()
        found: asyncio.Queue[EventKind] = asyncio.Queue()
        listener = hotkey.HotkeyListener(
            config.hotkeys,
            # ホットキーのスレッドから呼ばれる。ループへは種類だけを渡す
            lambda kind: loop.call_soon_threadsafe(found.put_nowait, kind),
        )
        failures = listener.start()
        try:
            for failure in failures:
                print(failure.message(), file=sys.stderr)
            if not listener.registered:
                print("登録できたホットキーがないため終了します。", file=sys.stderr)
                return False
            keys = "、".join(listener.registered)
            print(f"ホットキー（{keys}）を待っています。Ctrl+C で終了します。", flush=True)
            while True:
                print(await found.get(), flush=True)
        finally:
            # Ctrl+C のときも、スレッドを止めて登録を外す
            listener.stop()

    try:
        ok = asyncio.run(listen())
    except KeyboardInterrupt:
        print("終了しました。")
        return 0
    return 0 if ok else 2


def _run(args: argparse.Namespace, config: Config, microphone: audio.Microphone | None) -> int:
    try:
        token, created = load_or_create_token(default_token_dir(), reset=args.reset_token)
    except TokenStoreError as e:
        print(e, file=sys.stderr)
        return 2

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    if args.reset_token:
        print("トークンを作り直しました。OBS の URL を設定し直してください。")
    elif created:
        print("新しいトークンを作りました。OBS の URL を設定してください。")
    print("OBS のブラウザソースに次の URL を設定してください:")
    print(server.overlay_url(config.server.port, token))
    print("この URL を配信画面に映さないでください。", flush=True)
    if args.demo:
        print("デモモードで起動します。")
    server.serve(config, token, demo=args.demo, microphone=microphone)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
