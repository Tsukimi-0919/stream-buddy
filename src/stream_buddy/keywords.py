"""Vosk でキーワード (death / clear) を聞き取る (FR-07、ADR 0003)。

プライバシーと安全のため、次を守る。
- 音声は BlockQueue から受け取ったらすぐに Vosk に渡し、手元に残さない
- 認識した文字列は、どのキーワードかを判定したら捨てる。ファイル・ログ・コンソールに出さない
- 検知したときに外へ渡すのは、種類と、設定に書いたキーワードのうちどれか (Detection)。
  認識した文字列そのものは渡さない
- モデルは読み込む前に、同梱したハッシュの一覧と照合する (SR-07)。合わなければ読み込まない
- Vosk の結果は json.loads だけで読む。Vosk にはモデルのフォルダを必ず渡す (ネットから取得させない)
"""

import contextlib
import hashlib
import json
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from stream_buddy.audio import SAMPLE_RATE, BlockQueue, Samples
from stream_buddy.config import ConfigError, KeywordsConfig
from stream_buddy.state.events import EventKind

MODEL_NAME = "vosk-model-small-ja-0.22"
HASH_LIST_NAME = f"{MODEL_NAME}.sha256"
UNKNOWN = "[unk]"
MISSING_MODEL_MESSAGE = (
    "モデルがないためキーワード検知は無効です。取得方法は README を参照してください。"
    "（ホットキーは使えます）"
)
_TAKE_TIMEOUT_SECONDS = 0.1
# 部分結果で同じ判定がこの時間続いたら検知する (途中の結果の揺れで反応しないように)
PARTIAL_HOLD_MS = 150

type Clock = Callable[[], int]


def monotonic_ms() -> int:
    return int(time.monotonic() * 1000)


class KeywordError(ConfigError):
    """キーワード検知を準備できないときの例外 (起動しない)。"""


# モデルの場所と確認 (SR-07)


def default_model_dir() -> Path:
    """exe ならそのフォルダ、そうでなければカレントフォルダの models/<モデル名>。"""
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path.cwd()
    return base / "models" / MODEL_NAME


def resolve_model_dir(model_dir: str) -> Path:
    return Path(model_dir) if model_dir else default_model_dir()


def load_hash_list(text: str | None = None) -> dict[str, str]:
    """同梱したハッシュの一覧 ({相対パス: SHA-256})。"""
    if text is None:
        text = (resources.files("stream_buddy") / "data" / HASH_LIST_NAME).read_text(
            encoding="utf-8"
        )
    expected: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        digest, rel = line.split(maxsplit=1)
        expected[rel.strip()] = digest.lower()
    return expected


def verify_model(model_dir: Path, expected: Mapping[str, str] | None = None) -> int:
    """モデルのフォルダを一覧と照合し、照合したファイル数を返す。合わなければ KeywordError。"""
    expected = load_hash_list() if expected is None else expected
    actual = {p.relative_to(model_dir).as_posix(): p for p in model_dir.rglob("*") if p.is_file()}
    problems = [f"  ファイルがありません: {rel}" for rel in sorted(expected.keys() - actual.keys())]
    problems += [
        f"  一覧にないファイルがあります: {rel}" for rel in sorted(actual.keys() - expected.keys())
    ]
    for rel in sorted(expected.keys() & actual.keys()):
        if _sha256(actual[rel]) != expected[rel]:
            problems.append(f"  中身が違います（SHA-256 が一致しません）: {rel}")
    if problems:
        raise KeywordError(
            "音声認識モデルが、公式に配布されたものと一致しません。"
            "改ざんされているおそれがあるため、読み込みません。\n"
            + "\n".join(problems)
            + "\nモデルを公式サイトから取得し直してください（README を参照）。"
        )
    return len(expected)


def _sha256(path: Path) -> str:
    # このファイルでファイルを開くのは、ハッシュの確認のための読み込みだけ
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# 文法と判定

type Vocabulary = Callable[[str], bool]


def to_phrase(word: str, has_word: Vocabulary, where: str) -> str:
    """言葉を、Vosk の語彙の単語を空白でつないだ句にする。

    語彙にそのままあればそのまま。なければ、語彙の単語の最長一致で前から分ける。
    """
    parts: list[str] = []
    for piece in word.split():
        if has_word(piece):
            parts.append(piece)
            continue
        start = 0
        while start < len(piece):
            for end in range(len(piece), start, -1):
                if has_word(piece[start:end]):
                    parts.append(piece[start:end])
                    start = end
                    break
            else:
                raise KeywordError(
                    f"{where} の「{word}」は、音声認識の語彙で表せません"
                    f"（「{piece[start:]}」の部分を分けられません）。別の言い方にしてください"
                )
    return " ".join(parts)


def _contains(tokens: Sequence[str], phrase: Sequence[str]) -> bool:
    n = len(phrase)
    return n > 0 and any(tuple(tokens[i : i + n]) == tuple(phrase) for i in range(len(tokens)))


@dataclass(frozen=True)
class Detection:
    """検知したキーワード。word は設定に書いたキーワードそのもの (認識した文字列ではない)。"""

    kind: EventKind
    word: str


@dataclass(frozen=True)
class Grammar:
    """Vosk の文法と、認識結果からの判定。"""

    keywords: Mapping[EventKind, tuple[str, ...]]  # 種類ごとの句
    decoys: tuple[str, ...]
    # 句から、設定に書いたキーワードへ (ないときは句をそのまま使う)
    words: Mapping[str, str] = field(default_factory=dict)

    def to_json(self) -> str:
        phrases = [p for kind in ("death", "clear") for p in self.keywords.get(kind, ())]
        unique = list(dict.fromkeys([*phrases, *self.decoys]))
        return json.dumps([*unique, UNKNOWN], ensure_ascii=False)

    def judge(self, text: str) -> EventKind | None:
        """認識した文字列から、どのキーワードか。決められなければ None。"""
        detection = self.detect(text)
        return detection.kind if detection is not None else None

    def detect(self, text: str) -> Detection | None:
        """認識した文字列から、種類と設定に書いた言葉を決める。決められなければ None。"""
        tokens = text.split()
        if any(_contains(tokens, d.split()) for d in self.decoys):
            return None
        found = [
            (kind, matched)
            for kind, phrases in self.keywords.items()
            if (matched := [p for p in phrases if _contains(tokens, p.split())])
        ]
        # どちらか決められないときは、検知しない
        if len(found) != 1:
            return None
        kind, matched = found[0]
        return Detection(kind, self.words.get(matched[0], matched[0]))


def build_grammar(config: KeywordsConfig, has_word: Vocabulary) -> Grammar:
    death = tuple(to_phrase(w, has_word, "[keywords] death") for w in config.death)
    clear = tuple(to_phrase(w, has_word, "[keywords] clear") for w in config.clear)
    decoys = tuple(to_phrase(w, has_word, "[keywords] decoys") for w in config.decoys)
    # 句から設定の言葉へ。同じ句になる言葉が 2 つあれば、先に書いたほう
    words: dict[str, str] = {}
    for phrase, word in zip((*death, *clear), (*config.death, *config.clear), strict=True):
        words.setdefault(phrase, word)
    return Grammar({"death": death, "clear": clear}, decoys, words)


# 認識


class Recognizer(Protocol):
    # メソッド名は Vosk の KaldiRecognizer に合わせる
    def AcceptWaveform(self, data: bytes) -> bool: ...
    def Result(self) -> str: ...
    def PartialResult(self) -> str: ...


class LoadedModel(Protocol):
    def has_word(self, word: str) -> bool: ...
    def recognizer(self, grammar_json: str) -> Recognizer: ...


def _text_of(raw: str, key: str) -> str | None:
    result: Any = json.loads(raw)
    text = result.get(key) if isinstance(result, dict) else None
    return text if isinstance(text, str) else None


class KeywordSpotter:
    """音声のブロックを Vosk に渡し、部分結果と最終結果を判定する。

    - 部分結果で同じ種類の判定が PARTIAL_HOLD_MS 続いたら検知する
    - 1 つの発話 (最終結果で区切る) につき検知は 1 回まで。部分結果で検知した発話は、
      最終結果では検知しない。部分結果で検知しなかった発話は、最終結果で判定する
    """

    def __init__(self, recognizer: Recognizer, grammar: Grammar) -> None:
        self._recognizer = recognizer
        self._grammar = grammar
        # 部分結果で続いている判定と、その判定になった時刻
        self._candidate: EventKind | None = None
        self._candidate_since_ms = 0
        # この発話ですでに検知したか
        self._detected = False

    def feed(self, samples: Samples, now_ms: int) -> Detection | None:
        pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
        # 文字列は判定に使うだけで、どこにも残さない
        if self._recognizer.AcceptWaveform(pcm):
            return self._final(_text_of(self._recognizer.Result(), "text"))
        return self._partial(_text_of(self._recognizer.PartialResult(), "partial"), now_ms)

    def _final(self, text: str | None) -> Detection | None:
        detected = self._detected
        # 最終結果で発話が区切られる
        self._candidate = None
        self._detected = False
        if detected or text is None:
            return None
        return self._grammar.detect(text)

    def _partial(self, text: str | None, now_ms: int) -> Detection | None:
        if self._detected:
            return None
        detection = self._grammar.detect(text) if text is not None else None
        kind = detection.kind if detection is not None else None
        if kind != self._candidate:
            self._candidate = kind
            self._candidate_since_ms = now_ms
        if detection is None or now_ms - self._candidate_since_ms < PARTIAL_HOLD_MS:
            return None
        self._detected = True
        return detection


class KeywordListener:
    """認識用のスレッド。キューからブロックを取り出して判定し、検知したら on_keyword を呼ぶ。

    on_keyword には Detection を渡す。
    on_keyword はこのスレッドから呼ばれる (asyncio へは call_soon_threadsafe で渡すこと)。
    """

    def __init__(
        self,
        spotter: KeywordSpotter,
        blocks: BlockQueue,
        on_keyword: Callable[[Detection], object],
        *,
        clock: Clock = monotonic_ms,
    ) -> None:
        """clock は部分結果の判定が続いた時間を測るための時計 (ミリ秒)。"""
        self._spotter = spotter
        self._blocks = blocks
        self._on_keyword = on_keyword
        self._clock = clock
        self._stopping = threading.Event()
        self._thread = threading.Thread(target=self._run, name="keywords", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stopping.set()
        if self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._blocks.clear()

    def _run(self) -> None:
        while not self._stopping.is_set():
            block = self._blocks.take(_TAKE_TIMEOUT_SECONDS)
            if block is None:
                continue
            detection = self._spotter.feed(block, self._clock())
            del block
            if detection is not None:
                self._on_keyword(detection)


# 準備


class VoskModel:
    """本物の Vosk のモデル。モデルのフォルダを必ず渡し、ネットから取得させない。"""

    def __init__(self, model_dir: Path) -> None:
        import vosk  # type: ignore[import-untyped]

        vosk.SetLogLevel(-1)
        self._vosk = vosk
        try:
            # Vosk は日本語などを含むパスのモデルを開けないため、読み込む間だけ
            # カレントフォルダをモデルのフォルダにして相対パスで渡す
            # (起動時、他のスレッドが動く前に行う。docs/architecture.md の「既知の制約と回避策」)。
            # contextlib.chdir は、例外のときも必ず元のフォルダに戻す
            with contextlib.chdir(model_dir):
                self._model = vosk.Model(model_path=".")
        except Exception as e:
            raise KeywordError("音声認識モデルを読み込めません。") from e

    def has_word(self, word: str) -> bool:
        return bool(self._model.vosk_model_find_word(word) >= 0)

    def recognizer(self, grammar_json: str) -> Recognizer:
        recognizer: Recognizer = self._vosk.KaldiRecognizer(self._model, SAMPLE_RATE, grammar_json)
        return recognizer


@dataclass(frozen=True)
class KeywordSetup:
    model: LoadedModel
    grammar: Grammar

    def spotter(self) -> KeywordSpotter:
        return KeywordSpotter(self.model.recognizer(self.grammar.to_json()), self.grammar)


def prepare_keywords(
    config: KeywordsConfig,
    *,
    load_model: Callable[[Path], LoadedModel] = VoskModel,
    expected: Mapping[str, str] | None = None,
) -> KeywordSetup | None:
    """モデルを確かめて読み込み、文法を作る。

    無効、またはモデルのフォルダがないときは None (キーワード検知なしで起動する)。
    モデルが一覧と合わない・言葉を語彙で表せないときは KeywordError (起動しない)。
    """
    if not config.enabled:
        return None
    model_dir = resolve_model_dir(config.model_dir)
    if not model_dir.is_dir():
        return None
    verify_model(model_dir, expected)
    model = load_model(model_dir)
    return KeywordSetup(model, build_grammar(config, model.has_word))
