"""音声認識エンジンの比較 (T-06 のスパイク)。

Vosk と faster-whisper に同じ発話をかけ、キーワード検知の正解率・誤検知・処理時間を比べる。
結果は Markdown の表で標準出力に出す。ファイルには何も保存しない。

プライバシーのため、次を守る。
- 1 回の発話を最大 3 秒だけメモリに持ち、両方のエンジンにかけたらすぐに捨てる
- 音声をファイルに保存しない

使い方は spikes/README.md を参照。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

import numpy as np

from stream_buddy import audio
from stream_buddy.config import ConfigError, load_config
from stream_buddy.detect import SpeechDetector

if TYPE_CHECKING:
    from numpy.typing import NDArray

ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = ROOT / "models"
VOSK_MODEL_NAME = "vosk-model-small-ja-0.22"
VOSK_MODEL_DIR = MODELS_DIR / VOSK_MODEL_NAME
WHISPER_CACHE_DIR = MODELS_DIR / "faster-whisper"

KEYWORDS = ["死んだ", "やられた", "勝った", "クリア"]
NON_KEYWORDS = ["しんどい", "かったるい", "クリーム", "今日はいい天気"]
# Vosk の文法に渡す言い方。語彙にない場合は、語彙にある分け方 (例: "死ん だ") に書き換えて試す
VOSK_PHRASES = {keyword: keyword for keyword in KEYWORDS}

ENGINE_NAMES = ["vosk", "whisper-tiny", "whisper-base"]
MAX_SECONDS = 3.0
MAX_SAMPLES = int(MAX_SECONDS * audio.SAMPLE_RATE)
PRE_ROLL_BLOCKS = 10  # 話し始めの判定より前の 300 ms も含める
WAIT_SECONDS = 6.0  # Enter のあと、話し始めを待つ時間
LARGE_FILE_BYTES = 1_000_000  # これ以上のファイルを「主要なファイル」として SHA-256 を出す

VOSK_MANUAL_STEPS = f"""\
Vosk のモデルが見つかりません: models/{VOSK_MODEL_NAME}

次の手順で手動で取得してください (スクリプトからは取得しません)。
  1. 公式サイト https://alphacephei.com/vosk/models を開く
  2. 「{VOSK_MODEL_NAME}」の zip をダウンロードする
  3. リポジトリ直下の models/ に展開し、models/{VOSK_MODEL_NAME}/ ができるようにする
     (models/{VOSK_MODEL_NAME}/am や conf などのフォルダがあれば正しい)
詳しくは spikes/README.md を参照してください。
"""

type Audio = NDArray[np.float32]


class SpikeError(Exception):
    pass


# エンジン


def find_keyword(text: str) -> str | None:
    """書き起こしにキーワードが含まれていれば、そのキーワード (最初に見つかったもの)。"""
    compact = "".join(text.split())
    for keyword in KEYWORDS:
        if keyword in compact:
            return keyword
    return None


class Engine(Protocol):
    name: str
    load_ms: float
    model_dir: Path

    def transcribe(self, samples: Audio) -> str: ...


class VoskEngine:
    name = "vosk"

    def __init__(self) -> None:
        if not (VOSK_MODEL_DIR / "am").is_dir():
            raise SpikeError(VOSK_MANUAL_STEPS)
        import vosk

        vosk.SetLogLevel(-1)
        self.model_dir = VOSK_MODEL_DIR
        start = time.perf_counter()
        # パスを渡す。model_name や lang を渡すとネットから取得しようとするので使わない
        self._model = vosk.Model(model_path=str(VOSK_MODEL_DIR))
        self.load_ms = (time.perf_counter() - start) * 1000
        self._vosk = vosk
        self.missing_words = [
            word
            for phrase in VOSK_PHRASES.values()
            for word in phrase.split()
            if self._model.vosk_model_find_word(word) < 0
        ]
        # キーワードだけを候補にし、それ以外は [unk] として受け付ける
        self._grammar = json.dumps([*VOSK_PHRASES.values(), "[unk]"], ensure_ascii=False)

    def transcribe(self, samples: Audio) -> str:
        recognizer = self._vosk.KaldiRecognizer(self._model, audio.SAMPLE_RATE, self._grammar)
        pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
        recognizer.AcceptWaveform(pcm)
        text = str(json.loads(recognizer.FinalResult()).get("text", ""))
        return text.replace("[unk]", "").strip()


class WhisperEngine:
    def __init__(self, size: str) -> None:
        from faster_whisper import WhisperModel
        from faster_whisper.utils import download_model

        self.name = f"whisper-{size}"
        # 初回だけ Hugging Face から models/faster-whisper に取得する (このスパイクに限り許可)
        self.model_dir = Path(download_model(size, cache_dir=str(WHISPER_CACHE_DIR)))
        start = time.perf_counter()
        self._model = WhisperModel(str(self.model_dir), device="cpu", compute_type="int8")
        self.load_ms = (time.perf_counter() - start) * 1000

    def transcribe(self, samples: Audio) -> str:
        segments, _info = self._model.transcribe(samples, language="ja")
        return "".join(segment.text for segment in segments).strip()


def create_engine(name: str) -> Engine:
    if name == "vosk":
        return VoskEngine()
    if name in ("whisper-tiny", "whisper-base"):
        return WhisperEngine(name.removeprefix("whisper-"))
    raise SpikeError(f"知らないエンジンです: {name} (使えるもの: {', '.join(ENGINE_NAMES)})")


# 記録


@dataclass
class Trial:
    prompt: str
    expected: str | None
    detected: str | None
    text: str
    elapsed_ms: float
    cpu_ms: float

    @property
    def correct(self) -> bool:
        return self.detected == self.expected

    @property
    def false_detection(self) -> bool:
        """キーワードでない言葉で検知した、または違うキーワードとして検知した。"""
        return self.detected is not None and self.detected != self.expected


@dataclass
class EngineResult:
    engine: Engine
    trials: list[Trial] = field(default_factory=list)
    warmup_ms: float = 0.0

    def warm_up(self) -> None:
        """初回だけ遅いエンジンがあるため、測定の前に 1 回動かしておく (結果は記録しない)。

        無音だと Whisper は条件を変えて何度も書き起こし直して遅くなり、準備の時間と区別できない。
        そのため弱いノイズを使う。
        """
        noise = np.random.default_rng(1).standard_normal(audio.SAMPLE_RATE) * 0.01
        start = time.perf_counter()
        self.engine.transcribe(noise.astype(np.float32))
        self.warmup_ms = (time.perf_counter() - start) * 1000

    def run(self, prompt: str, expected: str | None, samples: Audio) -> Trial:
        cpu_start = time.process_time()
        start = time.perf_counter()
        text = self.engine.transcribe(samples)
        elapsed_ms = (time.perf_counter() - start) * 1000
        cpu_ms = (time.process_time() - cpu_start) * 1000
        trial = Trial(prompt, expected, find_keyword(text), text, elapsed_ms, cpu_ms)
        self.trials.append(trial)
        return trial


# 音声の取得 (本物のマイク)


def capture_utterance(stream: Any, threshold_db: float) -> Audio | None:
    """1 回の発話を最大 3 秒だけ取り出す。話し始めがなければ None。"""
    detector = SpeechDetector(threshold_db, audio.BLOCK_SECONDS)
    pre_roll: deque[Audio] = deque(maxlen=PRE_ROLL_BLOCKS)
    buffer = np.zeros(MAX_SAMPLES, dtype=np.float32)
    filled = 0
    wait_blocks = int(WAIT_SECONDS / audio.BLOCK_SECONDS)

    for _ in range(wait_blocks):
        block = _read_block(stream)
        pre_roll.append(block)
        if detector.update(audio.block_dbfs(block)):
            break
    else:
        pre_roll.clear()
        return None

    for block in pre_roll:
        filled = _append(buffer, filled, block)
    pre_roll.clear()
    while filled < MAX_SAMPLES:
        block = _read_block(stream)
        filled = _append(buffer, filled, block)
        if detector.update(audio.block_dbfs(block)) is False:
            break
    return buffer[:filled]


def _read_block(stream: Any) -> Audio:
    data, _overflowed = stream.read(audio.BLOCK_SIZE)
    return np.asarray(data[:, 0], dtype=np.float32).copy()


def _append(buffer: Audio, filled: int, block: Audio) -> int:
    n = min(len(block), MAX_SAMPLES - filled)
    buffer[filled : filled + n] = block[:n]
    return filled + n


def run_live(results: list[EngineResult], rounds: int, config_path: Path) -> None:
    import sounddevice

    config = load_config(config_path)
    threshold = config.audio.speech_threshold_db
    backend = audio.default_backend()
    device = audio.select_device(config.audio.device, backend.input_devices())
    prompts = [(word, word) for word in KEYWORDS] + [(word, None) for word in NON_KEYWORDS]
    total = rounds * len(prompts)

    print(f"しきい値: {threshold} dBFS。Ctrl+C で中断できます。\n")
    with sounddevice.InputStream(
        samplerate=audio.SAMPLE_RATE,
        blocksize=audio.BLOCK_SIZE,
        channels=1,
        dtype="float32",
        device=device,
    ) as stream:
        count = 0
        for round_index in range(rounds):
            for prompt, expected in prompts:
                count += 1
                print(f"[{count}/{total}] 第 {round_index + 1} 回: 「{prompt}」")
                while True:
                    input("  Enter を押してから話してください: ")
                    # Enter を待つあいだにたまった音は捨てる
                    if stream.read_available > 0:
                        stream.read(stream.read_available)
                    samples = capture_utterance(stream, threshold)
                    if samples is not None:
                        break
                    print("  声が聞き取れませんでした。もう一度どうぞ。")
                try:
                    for result in results:
                        trial = result.run(prompt, expected, samples)
                        mark = "OK" if trial.correct else "NG"
                        print(
                            f"  {mark} {result.engine.name}: {trial.detected or '検知なし'}"
                            f" ({trial.elapsed_ms:.0f} ms) 「{trial.text}」"
                        )
                finally:
                    # 同じ音声を全エンジンにかけたら、すぐに捨てる
                    samples.fill(0.0)
                    del samples
                print()


# 音声の代わりの配列 (マイクを開かない動作確認)


def run_self_test(results: list[EngineResult]) -> None:
    rng = np.random.default_rng(0)
    inputs: list[tuple[str, Audio]] = [
        ("無音 1 秒", np.zeros(audio.SAMPLE_RATE, dtype=np.float32)),
        ("ノイズ 1 秒", (rng.standard_normal(audio.SAMPLE_RATE) * 0.05).astype(np.float32)),
        ("ノイズ 3 秒", (rng.standard_normal(MAX_SAMPLES) * 0.3).astype(np.float32)),
    ]
    for label, samples in inputs:
        for result in results:
            trial = result.run(label, None, samples)
            print(
                f"  {result.engine.name} / {label}: {trial.detected or '検知なし'}"
                f" ({trial.elapsed_ms:.0f} ms) 「{trial.text}」"
            )
    print()


# 出力


def folder_info(directory: Path) -> tuple[int, list[tuple[str, int, str]]]:
    """フォルダの合計サイズと、主要なファイル (1 MB 以上) の SHA-256。"""
    total = 0
    large: list[tuple[str, int, str]] = []
    for path in sorted(p for p in directory.rglob("*") if p.is_file()):
        size = path.stat().st_size
        total += size
        if size >= LARGE_FILE_BYTES:
            large.append((path.relative_to(directory).as_posix(), size, _sha256(path)))
    return total, large


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _mb(size: int) -> str:
    return f"{size / 1_000_000:.1f} MB"


def print_report(results: list[EngineResult]) -> None:
    print("## 結果\n")
    columns = [
        "エンジン",
        "正解率",
        "誤検知",
        "処理時間 平均",
        "処理時間 最大",
        "CPU 時間 平均",
        "読み込み",
        "初回の準備",
        "モデルサイズ",
    ]
    print("| " + " | ".join(columns) + " |")
    print("|" + " --- |" * len(columns))
    for result in results:
        trials = result.trials
        n = len(trials)
        correct = sum(t.correct for t in trials)
        false_count = sum(t.false_detection for t in trials)
        elapsed = [t.elapsed_ms for t in trials] or [0.0]
        cpu = [t.cpu_ms for t in trials] or [0.0]
        size, _ = folder_info(result.engine.model_dir)
        print(
            f"| {result.engine.name} | {correct}/{n}"
            f" ({(correct / n * 100) if n else 0:.0f}%) | {false_count}"
            f" | {sum(elapsed) / len(elapsed):.0f} ms | {max(elapsed):.0f} ms"
            f" | {sum(cpu) / len(cpu):.0f} ms | {result.engine.load_ms:.0f} ms"
            f" | {result.warmup_ms:.0f} ms | {_mb(size)} |"
        )
    print(
        "\n- 誤検知：キーワードでない言葉で検知した、または違うキーワードとして検知した回数\n"
        "- CPU 時間：`time.process_time` の差。複数スレッドの合計なので、"
        "処理時間より大きくなることがある\n"
    )

    print("## 1 回ごとの結果\n")
    print("| エンジン | 読み上げ | 正解 | 判定 | 結果 | 処理時間 | 書き起こし |")
    print("| --- | --- | --- | --- | --- | --- | --- |")
    for result in results:
        for t in result.trials:
            print(
                f"| {result.engine.name} | {t.prompt} | {t.expected or '検知なし'}"
                f" | {t.detected or '検知なし'} | {'OK' if t.correct else 'NG'}"
                f" | {t.elapsed_ms:.0f} ms | {t.text.replace('|', '/')} |"
            )
    print()

    print("## モデル (SR-07 の材料)\n")
    for result in results:
        size, large = folder_info(result.engine.model_dir)
        print(f"### {result.engine.name}\n")
        print(f"- フォルダ：`{result.engine.model_dir.relative_to(ROOT).as_posix()}`")
        print(f"- 合計サイズ：{_mb(size)}")
        if isinstance(result.engine, VoskEngine) and result.engine.missing_words:
            print(f"- 語彙にない単語：{', '.join(result.engine.missing_words)}")
        print("\n| ファイル | サイズ | SHA-256 |")
        print("| --- | --- | --- |")
        for name, file_size, digest in large:
            print(f"| `{name}` | {_mb(file_size)} | `{digest}` |")
        print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="音声認識エンジンの比較 (T-06)")
    parser.add_argument(
        "--engines",
        default=",".join(ENGINE_NAMES),
        help=f"試すエンジン (カンマ区切り。既定: {','.join(ENGINE_NAMES)})",
    )
    parser.add_argument("--rounds", type=int, default=3, help="読み上げの回数 (既定: 3)")
    parser.add_argument(
        "--config", type=Path, default=Path("config.toml"), help="マイクとしきい値の設定ファイル"
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="マイクを開かず、無音とノイズの配列でエンジンが動くかだけを確かめる",
    )
    args = parser.parse_args(argv)
    if args.rounds < 1:
        parser.error("--rounds は 1 以上にしてください")

    # Hugging Face への利用状況の送信を止める (モデルの取得だけを行う)
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    # Windows ではシンボリックリンクが使えず、毎回警告が出るため止める (取得は問題なく動く)
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

    try:
        names = [name.strip() for name in args.engines.split(",") if name.strip()]
        results: list[EngineResult] = []
        for name in names:
            print(f"{name} のモデルを読み込んでいます…", flush=True)
            engine = create_engine(name)
            print(f"  読み込み: {engine.load_ms:.0f} ms")
            if isinstance(engine, VoskEngine) and engine.missing_words:
                print(
                    f"  注意: Vosk の語彙にない単語があります: {', '.join(engine.missing_words)}"
                    " (spikes/README.md の「Vosk の語彙」を参照)"
                )
            result = EngineResult(engine)
            result.warm_up()
            print(f"  初回の準備: {result.warmup_ms:.0f} ms")
            results.append(result)
        print()

        if args.self_test:
            run_self_test(results)
        else:
            run_live(results, args.rounds, args.config)
    except (SpikeError, ConfigError, audio.AudioError) as e:
        print(e, file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\n中断しました。ここまでの結果を表示します。\n")

    print_report(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
