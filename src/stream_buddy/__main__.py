"""stream-buddy のコマンドラインエントリポイント。"""

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from stream_buddy import __version__, audio, server
from stream_buddy.config import Config, ConfigError, load_config
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

    # デモのときはマイクを開かない
    microphone: audio.Microphone | None = None
    if not args.demo:
        try:
            backend = audio.default_backend()
            device = audio.select_device(config.audio.device, backend.input_devices())
            microphone = audio.Microphone(backend, device)
        except audio.AudioError as e:
            print(e, file=sys.stderr)
            return 2

    try:
        return _run(args, config, microphone)
    finally:
        # Ctrl+C やエラーで終わっても、ストリームを確実に閉じる
        if microphone is not None:
            microphone.close()


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
