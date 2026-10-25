"""stream-buddy のコマンドラインエントリポイント。"""

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from stream_buddy import __version__, server
from stream_buddy.config import ConfigError, load_config


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
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
    except ConfigError as e:
        print(e, file=sys.stderr)
        return 2

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    token = server.new_token()
    print("OBS のブラウザソースに次の URL を設定してください:")
    print(server.overlay_url(config.server.port, token))
    print("この URL を配信画面に映さないでください。", flush=True)
    if args.demo:
        print("デモモードで起動します。")
    server.serve(config, token, demo=args.demo)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
