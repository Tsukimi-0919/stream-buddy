"""stream-buddy のコマンドラインエントリポイント。"""

import argparse
from collections.abc import Sequence

from stream_buddy import __version__


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="stream-buddy")
    parser.add_argument("--version", action="version", version=__version__)
    parser.parse_args(argv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
