"""Vosk でキーワード (death / clear) を聞き取る (FR-07、ADR 0003)。

プライバシーと安全のため、次を守る。
- 音声は BlockQueue から受け取ったらすぐに Vosk に渡し、手元に残さない
- 認識した文字列は、どのキーワードかを判定したら捨てる。ファイル・ログ・コンソールに出さない
- モデルは読み込む前に、同梱したハッシュの一覧と照合する (SR-07)。合わなければ読み込まない
- Vosk の結果は json.loads だけで読む。Vosk にはモデルのフォルダを必ず渡す (ネットから取得させない)
"""

import contextlib
import hashlib
import json
import sys
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
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
class Grammar:
    """Vosk の文法と、認識結果からの判定。"""

    keywords: Mapping[EventKind, tuple[str, ...]]  # 種類ごとの句
    decoys: tuple[str, ...]

    def to_json(self) -> str:
        phrases = [p for kind in ("death", "clear") for p in self.keywords.get(kind, ())]
        unique = list(dict.fromkeys([*phrases, *self.decoys]))
        return json.dumps([*unique, UNKNOWN], ensure_ascii=False)

    def judge(self, text: str) -> EventKind | None:
        """認識した文字列から、どのキーワードか。決められなければ None。"""
        tokens = text.split()
        if any(_contains(tokens, d.split()) for d in self.decoys):
            return None
        kinds: list[EventKind] = [
            kind
            for kind, phrases in self.keywords.items()
            if any(_contains(tokens, p.split()) for p in phrases)
        ]
        # どちらか決められないときは、検知しない
        return kinds[0] if len(kinds) == 1 else None


def build_grammar(config: KeywordsConfig, has_word: Vocabulary) -> Grammar:
    death = tuple(to_phrase(w, has_word, "[keywords] death") for w in config.death)
    clear = tuple(to_phrase(w, has_word, "[keywords] clear") for w in config.clear)
    decoys = tuple(to_phrase(w, has_word, "[keywords] decoys") for w in config.decoys)
    return Grammar({"death": death, "clear": clear}, decoys)


# 認識


class Recognizer(Protocol):
    # メソッド名は Vosk の KaldiRecognizer に合わせる
    def AcceptWaveform(self, data: bytes) -> bool: ...
    def Result(self) -> str: ...


class LoadedModel(Protocol):
    def has_word(self, word: str) -> bool: ...
    def recognizer(self, grammar_json: str) -> Recognizer: ...


class KeywordSpotter:
    """音声のブロックを Vosk に渡し、最終結果が出るたびに判定する。"""

    def __init__(self, recognizer: Recognizer, grammar: Grammar) -> None:
        self._recognizer = recognizer
        self._grammar = grammar

    def feed(self, samples: Samples) -> EventKind | None:
        pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
        if not self._recognizer.AcceptWaveform(pcm):
            return None
        result: Any = json.loads(self._recognizer.Result())
        text = result.get("text") if isinstance(result, dict) else None
        # 文字列は判定に使うだけで、どこにも残さない
        return self._grammar.judge(text) if isinstance(text, str) else None


class KeywordListener:
    """認識用のスレッド。キューからブロックを取り出して判定し、検知したら on_keyword を呼ぶ。

    on_keyword はこのスレッドから呼ばれる (asyncio へは call_soon_threadsafe で渡すこと)。
    """

    def __init__(
        self, spotter: KeywordSpotter, blocks: BlockQueue, on_keyword: Callable[[EventKind], object]
    ) -> None:
        self._spotter = spotter
        self._blocks = blocks
        self._on_keyword = on_keyword
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
            kind = self._spotter.feed(block)
            del block
            if kind is not None:
                self._on_keyword(kind)


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
            # (起動時、他のスレッドが動く前に行う)
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
