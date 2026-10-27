"""配信ログ: テンション High・死亡・クリアの時刻を Markdown に書く (FR-10、SR-06)。

プライバシーと安全のため、次を守る。
- 書くのは、できごとの種類と時刻だけ。include_keyword = true のときだけ、検知した言葉
  (設定に書いたキーワードのどれか) を添える。音声・セリフ・トークン・パスは書かない
- ファイル名は日時からこのモジュールが作る。設定や外からの文字列をファイル名に使わない
- 書く前に resolve() で正規化し、ファイルが output_dir の直下にあることを確かめる
- ファイルは新規作成専用 ("x") で開き、上書きしない。output_dir のフォルダは作らない
- できごとのたびに 1 行書いて flush する (途中で落ちても、そこまでの行が残る)
"""

import logging
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import IO

from stream_buddy.config import ConfigError, LogConfig
from stream_buddy.state.events import EventKind

# 同じ名前のファイルがあるとき、-2、-3 … と付けて試す回数 (付けない名前を含む)
MAX_ATTEMPTS = 10

type WallClock = Callable[[], datetime]
type Monotonic = Callable[[], float]

logger = logging.getLogger(__name__)

_EFFECT_NAMES: dict[EventKind, str] = {"death": "死亡", "clear": "クリア"}
_PEAK = "テンション High"


class StreamLogError(ConfigError):
    """配信ログのファイルを用意できないときの例外 (起動しない)。メッセージにパスは含めない。"""


def file_names(started: datetime) -> list[str]:
    """試すファイル名を順に。起動した日時 (ローカル時刻) から作る。"""
    base = f"stream-buddy-{started:%Y-%m-%d-%H%M%S}"
    return [f"{base}.md", *(f"{base}-{n}.md" for n in range(2, MAX_ATTEMPTS + 1))]


def _cell(text: str) -> str:
    # 表が壊れないよう、| と改行を取り除く
    return "".join(ch for ch in text if ch not in "|\r\n")


def _clock_text(seconds: float, *, width: int) -> str:
    total = max(0, int(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours:0{width}d}:{minutes:02d}:{secs:02d}"


class StreamLog:
    """1 回の起動の配信ログ。open_stream_log で作る。"""

    def __init__(
        self,
        file: IO[str],
        *,
        include_keyword: bool,
        started: datetime,
        now: WallClock,
        monotonic: Monotonic,
    ) -> None:
        """started は起動した日時 (ファイル名と同じ)。経過はここで読んだ monotonic から数える。"""
        self._file = file
        self._include_keyword = include_keyword
        self._now = now
        self._monotonic = monotonic
        self._started = started
        self._started_mono = monotonic()
        self._counts = {_PEAK: 0, **{name: 0 for name in _EFFECT_NAMES.values()}}
        self._closed = False
        self._warned = False
        self._write(self._header())

    def _header(self) -> str:
        s = self._started
        return (
            "---\n"
            f"date: {s:%Y-%m-%d}\n"
            f'start: "{s:%H:%M:%S}"\n'
            "tags: [stream-buddy]\n"
            "---\n"
            f"# 配信ログ {s:%Y-%m-%d %H:%M}\n"
            "\n"
            "| 経過 | 時刻 | できごと |\n"
            "| --- | --- | --- |\n"
        )

    # できごと

    def peak(self) -> None:
        """テンションが High になった (TensionPeak)。"""
        self._record(_PEAK, _PEAK)

    def effect(self, kind: EventKind, word: str | None = None) -> None:
        """死亡・クリアの演出 (Effect)。word はキーワードで起きたときの、検知した言葉。"""
        name = _EFFECT_NAMES[kind]
        text = name
        if self._include_keyword and word:
            text = f"{name}（{_cell(word)}）"
        self._record(name, text)

    def _record(self, counted: str, text: str) -> None:
        if self._closed:
            return
        self._counts[counted] += 1
        elapsed = _clock_text(self._monotonic() - self._started_mono, width=2)
        self._write(f"| {elapsed} | {self._now():%H:%M:%S} | {_cell(text)} |\n")

    # 終わり

    def close(self) -> None:
        """まとめを書き足して閉じる。2 回目からは何もしない。"""
        if self._closed:
            return
        self._closed = True
        duration = _clock_text(self._monotonic() - self._started_mono, width=1)
        try:
            self._write(
                "\n## まとめ\n\n"
                f"- 配信時間：{duration}\n"
                f"- テンション High：{self._counts[_PEAK]} 回\n"
                f"- 死亡：{self._counts['死亡']} 回\n"
                f"- クリア：{self._counts['クリア']} 回\n"
            )
        finally:
            self._file.close()

    def _write(self, text: str) -> None:
        try:
            self._file.write(text)
            self._file.flush()
        except OSError:
            # 書けなくてもメンダコは止めない。パスは出さない
            if not self._warned:
                self._warned = True
                logger.warning("配信ログに書き込めませんでした（以降も書けない場合があります）")


def open_stream_log(
    config: LogConfig,
    *,
    now: WallClock = datetime.now,
    monotonic: Monotonic = time.monotonic,
) -> StreamLog | None:
    """enabled なら、output_dir の直下に新しいファイルを作る。無効なら None。

    output_dir がない・フォルダでない・書き込めないときは StreamLogError (起動しない)。
    """
    if not config.enabled:
        return None
    output_dir = Path(config.output_dir)
    if not output_dir.exists():
        raise StreamLogError(
            "[log] output_dir のフォルダがありません。フォルダを作ってから起動してください"
            "（stream-buddy はフォルダを作りません）"
        )
    if not output_dir.is_dir():
        raise StreamLogError("[log] output_dir にはフォルダを指定してください（ファイルです）")
    root = output_dir.resolve()
    started = now()
    for name in file_names(started):
        path = (root / name).resolve()
        # SR-06: 作るファイルが output_dir の直下にあることを確かめてから書く
        if path.parent != root:
            raise StreamLogError("[log] 配信ログの書き込み先が output_dir の外になります")
        try:
            file = path.open("x", encoding="utf-8", newline="\n")
        except FileExistsError:
            continue
        except OSError:
            raise StreamLogError(
                "[log] output_dir のフォルダに配信ログを書き込めません"
                "（書き込みの権限を確認してください）"
            ) from None
        return StreamLog(
            file,
            include_keyword=config.include_keyword,
            started=started,
            now=now,
            monotonic=monotonic,
        )
    raise StreamLogError(
        "[log] 同じ名前の配信ログがすでにあるため、新しいファイルを作れません"
        f"（{MAX_ATTEMPTS} 回試しました）"
    )
