"""stream-buddy のコマンドラインエントリポイント。"""

import argparse
import asyncio
import contextlib
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from stream_buddy import __version__, app, audio, hotkey, keywords, lines, server, stream_log
from stream_buddy.config import Config, ConfigError, load_config
from stream_buddy.detect import SpeechDetector
from stream_buddy.state.events import EventKind, Hotkey
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
    parser.add_argument(
        "--debug",
        action="store_true",
        help="確認用に、盛り上がり度とテンションなどの状態を 2 秒ごとにコンソールに表示する",
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

    if args.test_keywords:
        return _run_test_keywords(config)

    return _start(args, config)


def _start(args: argparse.Namespace, config: Config) -> int:
    """起動する (docs/architecture.md の「起動の流れ」)。終了は逆の順番で行う。"""
    # 2. セリフ集を読み、検証する。配信ログが有効なら、ほかを始める前にファイルを作る
    try:
        book = lines.load_lines(config.lines.file)
        log = stream_log.open_stream_log(config.log)
    except ConfigError as e:
        print(e, file=sys.stderr)
        return 2
    try:
        return _run(args, config, book, log)
    finally:
        # Ctrl+C や例外で終わっても、まとめを書いて閉じる
        if log is not None:
            log.close()


def _run(
    args: argparse.Namespace,
    config: Config,
    book: lines.LineBook,
    log: stream_log.StreamLog | None,
) -> int:
    # 3. トークンを読む (なければ作る)
    try:
        token, created = load_or_create_token(default_token_dir(), reset=args.reset_token)
    except TokenStoreError as e:
        print(e, file=sys.stderr)
        return 2

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    engine = app.Engine(config, book, debug=_print_debug if args.debug else None, log=log)

    # デモのときはマイクも音声認識もホットキーも使わず、偽の入力を Brain に入れる
    if args.demo:
        _print_url(args, config, token, created=created)
        print("デモモードで起動します。", flush=True)
        runtime = app.Runtime(engine, config, demo=True)
        server.serve(config, token, running=runtime.run, state_messages=engine.state_messages)
        print("終了しました。")
        return 0

    # 4. モデルを確認して読み込む (ほかのスレッドが動き出す前。docs/architecture.md の既知の制約)
    try:
        setup = keywords.prepare_keywords(config.keywords)
    except ConfigError as e:
        print(e, file=sys.stderr)
        return 2
    if setup is None and config.keywords.enabled:
        print(keywords.MISSING_MODEL_MESSAGE)

    listener: hotkey.HotkeyListener | None = None
    microphone: audio.Microphone | None = None
    try:
        # 5. ホットキーを登録する。1 つも登録できなくても起動は続ける
        listener = hotkey.HotkeyListener(
            config.hotkeys,
            # ホットキーのスレッドから呼ばれる。渡すのはキーの種類だけ
            lambda kind: engine.submit_threadsafe(Hotkey(kind)),
        )
        for failure in listener.start():
            print(failure.message(), file=sys.stderr)
        if not listener.registered:
            print(
                "ホットキーを 1 つも登録できなかったため、ホットキーなしで起動します。",
                file=sys.stderr,
            )

        # 6. マイクを選び、ストリームを用意する (見つからなければ起動しない)。
        # URL を表示する前に知らせるため、ここで行う。音を取り始めるのはサーバーの起動後
        microphone = _open_microphone(config)
        if microphone is None:
            return 2

        # 7. サーバーを起動し、OBS の URL を表示する
        # (8. マイクと認識用のスレッド、9. 時計とキューの処理は、
        #  サーバーの起動後に Runtime が始める)
        _print_url(args, config, token, created=created)
        runtime = app.Runtime(engine, config, microphone=microphone, keywords=setup)
        server.serve(config, token, running=runtime.run, state_messages=engine.state_messages)
        print("終了しました。")
        return 0
    finally:
        # Ctrl+C や例外で終わっても、マイクを閉じ、ホットキーの登録を外す
        if microphone is not None:
            microphone.close()
        if listener is not None:
            listener.stop()


def _open_microphone(config: Config) -> audio.Microphone | None:
    try:
        backend = audio.default_backend()
        device = audio.select_device(config.audio.device, backend.input_devices())
        return audio.Microphone(backend, device)
    except audio.AudioError as e:
        print(e, file=sys.stderr)
        return None


def _print_url(args: argparse.Namespace, config: Config, token: str, *, created: bool) -> None:
    if args.reset_token:
        print("トークンを作り直しました。OBS の URL を設定し直してください。")
    elif created:
        print("新しいトークンを作りました。OBS の URL を設定してください。")
    print("OBS のブラウザソースに次の URL を設定してください:")
    print(server.overlay_url(config.server.port, token))
    print("この URL を配信画面に映さないでください。", flush=True)


def _print_debug(line: str) -> None:
    # 中身は app.format_debug などが作る、数値と状態の名前だけの行
    print(line, flush=True)


def _run_test_keywords(config: Config) -> int:
    try:
        setup = keywords.prepare_keywords(config.keywords)
    except ConfigError as e:
        print(e, file=sys.stderr)
        return 2
    if setup is None:
        if config.keywords.enabled:
            print(keywords.MISSING_MODEL_MESSAGE)
        print("キーワード検知が無効なため、--test-keywords は使えません。", file=sys.stderr)
        return 2
    microphone = _open_microphone(config)
    if microphone is None:
        return 2
    try:
        return _test_keywords(microphone, setup, config.audio.speech_threshold_db)
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


class ReactionTimer:
    """--test-keywords の表示を作る。話し終わり (detect) から検知までの時間を添える。

    話し終わる前に検知したときは、話し終わるまで表示を待ち、負の値で示す。
    """

    def __init__(self) -> None:
        self._speaking = False
        self._ended_ms: int | None = None
        self._waiting: list[tuple[EventKind, int]] = []

    def speech(self, *, speaking: bool, now_ms: int) -> list[str]:
        self._speaking = speaking
        if speaking:
            return []
        self._ended_ms = now_ms
        lines = [_reaction(kind, found_ms - now_ms) for kind, found_ms in self._waiting]
        self._waiting.clear()
        return lines

    def keyword(self, kind: EventKind, now_ms: int) -> list[str]:
        if self._speaking:
            self._waiting.append((kind, now_ms))
            return []
        if self._ended_ms is None:
            return [f"{kind} (話し終わりを検出していません)"]
        return [_reaction(kind, now_ms - self._ended_ms)]


def _reaction(kind: EventKind, delay_ms: int) -> str:
    return f"{kind} ({delay_ms} ms)"


def _test_keywords(
    microphone: audio.Microphone,
    setup: keywords.KeywordSetup,
    threshold_db: float,
    clock: keywords.Clock = keywords.monotonic_ms,
) -> int:
    """聞き取ったキーワードの種類と、話し終わりからの時間だけを表示する。認識した文字列は出さない。"""

    async def listen() -> None:
        loop = asyncio.get_running_loop()
        found: asyncio.Queue[str] = asyncio.Queue()
        blocks = audio.BlockQueue()
        detector = SpeechDetector(threshold_db, audio.BLOCK_SECONDS)
        timer = ReactionTimer()

        def show(lines: list[str]) -> None:
            for line in lines:
                found.put_nowait(line)

        def on_level_in_loop(level_db: float, now_ms: int) -> None:
            changed = detector.update(level_db)
            if changed is not None:
                show(timer.speech(speaking=changed, now_ms=now_ms))

        def on_level(level_db: float) -> None:
            # 音声のスレッドから呼ばれる。渡すのは音量の数値と時刻だけ
            with contextlib.suppress(RuntimeError):  # 終了処理中でループが閉じている
                loop.call_soon_threadsafe(on_level_in_loop, level_db, clock())

        def on_keyword_in_loop(kind: EventKind, found_ms: int) -> None:
            show(timer.keyword(kind, found_ms))

        listener = keywords.KeywordListener(
            setup.spotter(),
            blocks,
            # 認識用のスレッドから呼ばれる。ループへは種類と時刻だけを渡す (言葉は表示しない)
            lambda detection: loop.call_soon_threadsafe(
                on_keyword_in_loop, detection.kind, clock()
            ),
            clock=clock,
        )
        microphone.set_sample_sink(blocks.offer)
        microphone.start(on_level)
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


if __name__ == "__main__":
    raise SystemExit(main())
