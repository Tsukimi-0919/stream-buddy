"""キーワード検知のテスト。本物のモデルとマイクは使わない (CI にないため)。"""

import ast
import hashlib
import json
import re
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest
from conftest import FakeBackend, FakeStream

import stream_buddy.__main__ as main_module
from stream_buddy import keywords
from stream_buddy.__main__ import main
from stream_buddy.audio import BLOCK_SIZE, BlockQueue
from stream_buddy.config import ConfigError, KeywordsConfig, load_config
from stream_buddy.keywords import (
    Detection,
    Grammar,
    KeywordError,
    KeywordListener,
    KeywordSpotter,
    build_grammar,
    load_hash_list,
    prepare_keywords,
    to_phrase,
    verify_model,
)

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "stream_buddy" / "keywords.py"
ADR = ROOT / "docs" / "adr" / "0003-asr-engine.md"

# 偽の語彙。「死んだ」「勝った」は 1 語では入っていない (本物の語彙と同じ)
VOCAB = {
    "死ん", "死", "だ", "た", "やられた", "クリア", "やったー", "ナイス",
    "やっぱり", "クリーム", "しんどい", "かったるい", "勝っ", "ん",
}  # fmt: skip


def has_word(word: str) -> bool:
    return word in VOCAB


# 設定


def write_config(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(text, encoding="utf-8")
    return path


def config_error(tmp_path: Path, text: str) -> str:
    with pytest.raises(ConfigError) as exc:
        load_config(write_config(tmp_path, text))
    return str(exc.value)


def test_default_keywords_follow_adr_0003() -> None:
    config = KeywordsConfig()
    assert config.death == ("死んだ", "やられた")
    assert config.clear == ("クリア", "やったー")
    assert "勝った" not in config.clear
    assert config.decoys == ("やっぱり", "クリーム", "しんどい", "かったるい")


def test_keyword_and_decoy_overlap_is_error(tmp_path: Path) -> None:
    message = config_error(tmp_path, '[keywords]\ndecoys = ["クリア", "クリーム"]\n')
    assert "[keywords] キーワード（death・clear）とおとり（decoys）に同じ言葉があります" in message
    assert "クリア" in message


def test_death_and_clear_overlap_is_error(tmp_path: Path) -> None:
    text = '[keywords]\ndeath = ["死んだ", "終わった"]\nclear = ["クリア", "終わった"]\n'
    message = config_error(tmp_path, text)
    assert "[keywords] death と clear に同じ言葉があります（終わった）" in message


def test_decoys_can_be_empty(tmp_path: Path) -> None:
    assert load_config(write_config(tmp_path, "[keywords]\ndecoys = []\n")).keywords.decoys == ()


def test_too_many_decoys_is_error(tmp_path: Path) -> None:
    decoys = ", ".join(f'"おとり{i}"' for i in range(21))
    assert "最大 20 個" in config_error(tmp_path, f"[keywords]\ndecoys = [{decoys}]\n")


@pytest.mark.parametrize("model_dir", ["models", "models\\vosk", "C:models", "\\models"])
def test_relative_model_dir_is_error(tmp_path: Path, model_dir: str) -> None:
    message = config_error(tmp_path, f"[keywords]\nmodel_dir = '{model_dir}'\n")
    assert "[keywords] model_dir は 絶対パスで指定してください" in message
    # パスには個人のフォルダ名が入りうるので、指定値は出さない
    assert "指定値" not in message


def test_absolute_model_dir_is_ok(tmp_path: Path) -> None:
    config = load_config(write_config(tmp_path, "[keywords]\nmodel_dir = 'D:\\models\\ja'\n"))
    assert config.keywords.model_dir == "D:\\models\\ja"


# モデルの確認 (SR-07)


def make_fake_model(root: Path) -> tuple[Path, dict[str, str]]:
    """小さな偽モデルと、そのハッシュの一覧を作る。"""
    model = root / "models" / keywords.MODEL_NAME
    files = {"am/final.mdl": b"acoustic", "graph/words.txt": b"<eps> 0\n", "README": b""}
    for rel, data in files.items():
        (model / rel).parent.mkdir(parents=True, exist_ok=True)
        (model / rel).write_bytes(data)
    return model, {rel: hashlib.sha256(data).hexdigest() for rel, data in files.items()}


def test_bundled_hash_list_matches_adr_0003() -> None:
    expected = load_hash_list()
    assert len(expected) == 16
    recorded = re.findall(
        r"^\| `([^`]+)` \| [^|]+ \| `([0-9a-f]{64})` \|$",
        ADR.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    assert len(recorded) == 5
    for rel, digest in recorded:
        assert expected[rel] == digest


def test_verify_model_ok(tmp_path: Path) -> None:
    model, expected = make_fake_model(tmp_path)
    assert verify_model(model, expected) == 3


def test_verify_model_missing_file(tmp_path: Path) -> None:
    model, expected = make_fake_model(tmp_path)
    (model / "am" / "final.mdl").unlink()
    with pytest.raises(KeywordError, match=r"ファイルがありません: am/final\.mdl"):
        verify_model(model, expected)


def test_verify_model_hash_mismatch(tmp_path: Path) -> None:
    model, expected = make_fake_model(tmp_path)
    (model / "graph" / "words.txt").write_bytes(b"<eps> 0\nevil 1\n")
    with pytest.raises(KeywordError, match=r"中身が違います.*: graph/words\.txt"):
        verify_model(model, expected)


def test_verify_model_extra_file(tmp_path: Path) -> None:
    model, expected = make_fake_model(tmp_path)
    (model / "graph" / "extra.dll").write_bytes(b"MZ")
    with pytest.raises(KeywordError, match=r"一覧にないファイルがあります: graph/extra\.dll"):
        verify_model(model, expected)


def test_verify_model_reports_all_problems(tmp_path: Path) -> None:
    model, expected = make_fake_model(tmp_path)
    (model / "README").unlink()
    (model / "am" / "final.mdl").write_bytes(b"changed")
    with pytest.raises(KeywordError) as exc:
        verify_model(model, expected)
    message = str(exc.value)
    assert "改ざんされているおそれ" in message
    assert "README" in message
    assert "am/final.mdl" in message


# 分割と文法


def test_word_in_vocabulary_is_kept() -> None:
    assert to_phrase("クリア", has_word, "[keywords] clear") == "クリア"


def test_word_is_split_by_longest_match() -> None:
    # 「死」と「死ん」の両方があっても、長い「死ん」を選ぶ
    assert to_phrase("死んだ", has_word, "[keywords] death") == "死ん だ"
    assert to_phrase("勝った", has_word, "[keywords] clear") == "勝っ た"


def test_words_with_spaces_are_split_per_piece() -> None:
    assert to_phrase("死んだ クリア", has_word, "[keywords] death") == "死ん だ クリア"


def test_unsplittable_word_is_error() -> None:
    with pytest.raises(KeywordError) as exc:
        to_phrase("死んでる", has_word, "[keywords] death")
    message = str(exc.value)
    assert "[keywords] death の「死んでる」" in message
    assert "「でる」の部分" in message


def test_grammar_json_has_keywords_decoys_and_unk() -> None:
    grammar = build_grammar(KeywordsConfig(), has_word)
    assert json.loads(grammar.to_json()) == [
        "死ん だ",
        "やられた",
        "クリア",
        "やったー",
        "やっぱり",
        "クリーム",
        "しんどい",
        "かったるい",
        "[unk]",
    ]


def test_build_grammar_reports_which_setting() -> None:
    config = KeywordsConfig(decoys=("ほげ",))
    with pytest.raises(KeywordError, match=r"\[keywords\] decoys の「ほげ」"):
        build_grammar(config, has_word)


# 判定

GRAMMAR = Grammar(
    {"death": ("死ん だ", "やられた"), "clear": ("クリア", "やったー")}, ("クリーム",)
)


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("死ん だ", "death"),
        ("[unk] やられた", "death"),
        ("クリア", "clear"),
        ("やったー [unk]", "clear"),
        ("クリーム", None),  # おとりだけ
        ("クリーム クリア", None),  # おとりとキーワード
        ("死ん だ クリア", None),  # 2 種類
        ("[unk]", None),
        ("", None),
        ("死ん", None),  # 句の一部だけ
        ("だ 死ん", None),  # 順番が違う
    ],
)
def test_judge(text: str, kind: str | None) -> None:
    assert GRAMMAR.judge(text) == kind


WORDS_GRAMMAR = Grammar(
    {"death": ("死ん だ", "やられた"), "clear": ("クリア", "やったー")},
    ("クリーム",),
    {"死ん だ": "死んだ", "やられた": "やられた", "クリア": "クリア", "やったー": "やったー"},
)


@pytest.mark.parametrize(
    ("text", "detection"),
    [
        ("死ん だ", Detection("death", "死んだ")),
        ("[unk] やられた", Detection("death", "やられた")),
        ("やったー [unk]", Detection("clear", "やったー")),
        ("やられた 死ん だ", Detection("death", "死んだ")),  # 同じ種類が 2 つなら、先に書いた言葉
        ("クリーム クリア", None),
        ("死ん だ クリア", None),
    ],
)
def test_detect_returns_configured_word(text: str, detection: Detection | None) -> None:
    assert WORDS_GRAMMAR.detect(text) == detection


def test_detect_word_is_from_config_not_recognized_text() -> None:
    # 認識結果にキーワード以外の言葉が混ざっても、渡すのは設定の言葉だけ
    found = WORDS_GRAMMAR.detect("[unk] 死ん だ [unk]")
    assert found == Detection("death", "死んだ")
    assert "[unk]" not in found.word


def test_build_grammar_maps_phrases_to_configured_words() -> None:
    grammar = build_grammar(KeywordsConfig(), has_word)
    assert grammar.words["死ん だ"] == "死んだ"
    assert set(grammar.words.values()) == {"死んだ", "やられた", "クリア", "やったー"}
    assert grammar.detect("死ん だ") == Detection("death", "死んだ")


def test_spotter_returns_word_from_partial_results() -> None:
    spotter = KeywordSpotter(FakeRecognizer([Partial("死ん だ")] * 2), WORDS_GRAMMAR)
    assert spotter.feed(block(), 0) is None
    assert spotter.feed(block(), 150) == Detection("death", "死んだ")


@dataclass(frozen=True)
class Partial:
    """FakeRecognizer に渡す部分結果 (最終結果は出ない)。"""

    text: str


class FakeRecognizer:
    """偽の Vosk。1 ブロックごとに、用意した結果を順に返す。

    文字列は最終結果 (AcceptWaveform が True)、Partial は部分結果、None は空の部分結果。
    """

    def __init__(self, results: list[str | Partial | None]) -> None:
        self.results = list(results)
        self.received: list[bytes] = []
        self._current = ""
        self._partial = ""

    def AcceptWaveform(self, data: bytes) -> bool:
        self.received.append(data)
        result = self.results.pop(0) if self.results else None
        if isinstance(result, str):
            self._current = result
            self._partial = ""
            return True
        self._partial = result.text if result is not None else ""
        return False

    def Result(self) -> str:
        return self._current

    def PartialResult(self) -> str:
        return json.dumps({"partial": self._partial}, ensure_ascii=False)


def block(value: float = 0.1) -> np.ndarray:
    return np.full(BLOCK_SIZE, value, dtype=np.float32)


def final(text: str) -> str:
    return json.dumps({"text": text}, ensure_ascii=False)


def feed_all(spotter: KeywordSpotter, times_ms: list[int]) -> list[str | None]:
    """検知した種類 (検知しなければ None) の一覧。"""
    found = [spotter.feed(block(), now) for now in times_ms]
    return [d.kind if d is not None else None for d in found]


def test_spotter_judges_final_results() -> None:
    recognizer = FakeRecognizer([None, final("死ん だ"), final("クリーム")])
    spotter = KeywordSpotter(recognizer, GRAMMAR)
    assert feed_all(spotter, [0, 30, 60]) == [None, "death", None]  # 途中、検知、おとり
    # Vosk には 16 bit の PCM で渡す
    assert len(recognizer.received[0]) == BLOCK_SIZE * 2


@pytest.mark.parametrize("result", ["[]", '{"text": 1}', "{}", '"死ん だ"'])
def test_spotter_ignores_unexpected_results(result: str) -> None:
    spotter = KeywordSpotter(FakeRecognizer([result]), GRAMMAR)
    assert spotter.feed(block(), 0) is None


@pytest.mark.parametrize("result", ["[]", '{"partial": 1}', "{}", '"死ん だ"'])
def test_spotter_ignores_unexpected_partial_results(result: str) -> None:
    recognizer = FakeRecognizer([None, None])
    recognizer.PartialResult = lambda: result  # type: ignore[method-assign]
    spotter = KeywordSpotter(recognizer, GRAMMAR)
    assert feed_all(spotter, [0, 1_000]) == [None, None]


# 部分結果


def test_partial_keyword_held_150ms_is_detected() -> None:
    spotter = KeywordSpotter(FakeRecognizer([Partial("やったー")] * 3), GRAMMAR)
    assert feed_all(spotter, [1_000, 1_100, 1_150]) == [None, None, "clear"]
    assert keywords.PARTIAL_HOLD_MS == 150


def test_partial_keyword_held_149ms_is_not_detected() -> None:
    spotter = KeywordSpotter(FakeRecognizer([Partial("死ん だ")] * 2), GRAMMAR)
    assert feed_all(spotter, [1_000, 1_149]) == [None, None]


def test_partial_that_changes_midway_is_not_detected() -> None:
    # 途中の結果で一瞬「やったー」に見えても、「やっぱり」に変われば反応しない
    results = [Partial("やったー"), Partial("やったー"), Partial("やっぱり"), Partial("やっぱり")]
    spotter = KeywordSpotter(FakeRecognizer([*results, final("やっぱり")]), GRAMMAR)
    assert feed_all(spotter, [0, 100, 140, 400, 430]) == [None] * 5


def test_partial_count_restarts_after_change() -> None:
    results = [Partial("やったー"), Partial("[unk]"), Partial("やったー"), Partial("やったー")]
    spotter = KeywordSpotter(FakeRecognizer(results), GRAMMAR)
    # 判定が変わったら、また同じ判定になってから 150 ms を数え直す
    assert feed_all(spotter, [0, 100, 200, 350]) == [None, None, None, "clear"]


def test_partial_with_decoy_is_not_detected() -> None:
    spotter = KeywordSpotter(FakeRecognizer([Partial("クリーム クリア")] * 3), GRAMMAR)
    assert feed_all(spotter, [0, 150, 300]) == [None, None, None]


def test_partial_detection_is_once_per_utterance() -> None:
    results = [Partial("死ん だ")] * 4 + [final("死ん だ")]
    spotter = KeywordSpotter(FakeRecognizer(results), GRAMMAR)
    # 部分結果で 1 回検知したら、その発話の最終結果でも、続く部分結果でも検知しない
    assert feed_all(spotter, [0, 150, 300, 450, 480]) == [None, "death", None, None, None]


def test_next_utterance_is_judged_after_final() -> None:
    results = [Partial("死ん だ"), Partial("死ん だ"), final("死ん だ")]
    results += [Partial("やったー"), Partial("やったー")]
    spotter = KeywordSpotter(FakeRecognizer(results), GRAMMAR)
    # 最終結果で発話が区切られ、次の発話はまた検知できる
    assert feed_all(spotter, [0, 150, 200, 1_000, 1_150]) == [None, "death", None, None, "clear"]


def test_utterance_not_detected_by_partial_is_judged_by_final() -> None:
    # 部分結果では 150 ms 続かなかった発話も、最終結果で検知する
    spotter = KeywordSpotter(FakeRecognizer([Partial("やったー"), final("やったー")]), GRAMMAR)
    assert feed_all(spotter, [0, 30]) == [None, "clear"]


def test_listener_calls_on_keyword_from_thread() -> None:
    spotter = KeywordSpotter(FakeRecognizer([None, json.dumps({"text": "やったー"})]), GRAMMAR)
    blocks = BlockQueue()
    found: list[str] = []
    done = threading.Event()

    def on_keyword(detection: Detection) -> None:
        found.append(detection.kind)
        done.set()

    listener = KeywordListener(spotter, blocks, on_keyword)
    listener.start()
    blocks.offer(block())
    blocks.offer(block())
    assert done.wait(5.0)
    listener.stop()
    assert found == ["clear"]
    assert blocks.size() == 0


def test_listener_uses_given_clock_for_partial_results() -> None:
    spotter = KeywordSpotter(FakeRecognizer([Partial("やったー")] * 2), GRAMMAR)
    blocks = BlockQueue()
    found: list[str] = []
    done = threading.Event()
    times = iter([0, 150])

    def on_keyword(detection: Detection) -> None:
        found.append(detection.kind)
        done.set()

    listener = KeywordListener(spotter, blocks, on_keyword, clock=lambda: next(times))
    listener.start()
    blocks.offer(block())
    blocks.offer(block())
    assert done.wait(5.0)
    listener.stop()
    assert found == ["clear"]


# 準備


class FakeModel:
    def __init__(self, results: list[str | None] | None = None) -> None:
        self.results = results or []
        self.grammars: list[str] = []

    def has_word(self, word: str) -> bool:
        return has_word(word)

    def recognizer(self, grammar_json: str) -> FakeRecognizer:
        self.grammars.append(grammar_json)
        return FakeRecognizer(self.results)


class FakeVoskModule:
    """偽の vosk モジュール。Model を作るときのカレントフォルダを記録する。"""

    def __init__(self, fail: bool) -> None:
        self.fail = fail
        self.cwd_during_load: Path | None = None
        self.model_paths: list[str] = []

    def SetLogLevel(self, _level: int) -> None:
        pass

    def Model(self, model_path: str) -> object:
        self.model_paths.append(model_path)
        self.cwd_during_load = Path.cwd()
        if self.fail:
            raise Exception("Failed to create a model")  # Vosk と同じ例外
        return object()


@pytest.mark.parametrize("fail", [False, True])
def test_vosk_model_loads_from_model_dir_and_restores_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fail: bool
) -> None:
    fake = FakeVoskModule(fail)
    monkeypatch.setitem(sys.modules, "vosk", fake)
    model_dir = tmp_path / "日本語のフォルダ" / keywords.MODEL_NAME
    model_dir.mkdir(parents=True)
    before = Path.cwd()

    if fail:
        with pytest.raises(KeywordError, match="読み込めません"):
            keywords.VoskModel(model_dir)
    else:
        keywords.VoskModel(model_dir)

    # 読み込む間だけモデルのフォルダに移り、相対パスで渡す。例外が起きても元に戻る
    assert fake.cwd_during_load is not None
    assert fake.cwd_during_load.resolve() == model_dir.resolve()
    assert fake.model_paths == ["."]
    assert Path.cwd() == before


def test_prepare_disabled_does_not_look_for_model() -> None:
    def fail(_: Path) -> FakeModel:
        raise AssertionError("読み込まない")

    assert prepare_keywords(KeywordsConfig(enabled=False), load_model=fail) is None


def test_prepare_without_model_folder_returns_none(no_real_model: Path) -> None:
    assert not no_real_model.exists()
    assert prepare_keywords(KeywordsConfig(), load_model=lambda _: FakeModel()) is None


def test_prepare_verifies_before_loading(tmp_path: Path) -> None:
    model, expected = make_fake_model(tmp_path)
    (model / "README").write_bytes(b"tampered")
    loaded: list[Path] = []

    def load(path: Path) -> FakeModel:
        loaded.append(path)
        return FakeModel()

    config = KeywordsConfig(model_dir=str(model))
    with pytest.raises(KeywordError):
        prepare_keywords(config, load_model=load, expected=expected)
    assert loaded == []  # 改ざんされたモデルは読み込まない


def test_prepare_builds_grammar(tmp_path: Path) -> None:
    model, expected = make_fake_model(tmp_path)
    fake = FakeModel([json.dumps({"text": "死ん だ"})])
    config = KeywordsConfig(model_dir=str(model))
    setup = prepare_keywords(config, load_model=lambda _: fake, expected=expected)
    assert setup is not None
    # 渡すのは、句 (死ん だ) ではなく設定に書いた言葉
    assert setup.spotter().feed(block(), 0) == Detection("death", "死んだ")
    assert "死ん だ" in json.loads(fake.grammars[0])


def test_prepare_uses_default_model_dir(no_real_model: Path) -> None:
    _, expected = make_fake_model(no_real_model.parent.parent)
    setup = prepare_keywords(KeywordsConfig(), load_model=lambda _: FakeModel(), expected=expected)
    assert setup is not None


# 起動のオプション


@pytest.fixture
def fake_model_installed(no_real_model: Path, monkeypatch: pytest.MonkeyPatch) -> FakeModel:
    """既定の場所に偽モデルを置き、ハッシュの一覧と読み込みを偽物に差し替える。"""
    _, expected = make_fake_model(no_real_model.parent.parent)
    monkeypatch.setattr(keywords, "load_hash_list", lambda: expected)
    fake = FakeModel([None, json.dumps({"text": "死ん だ"})])
    monkeypatch.setattr(keywords, "VoskModel", lambda _: fake)
    original = keywords.prepare_keywords
    monkeypatch.setattr(
        keywords,
        "prepare_keywords",
        lambda config: original(config, load_model=lambda _: fake, expected=expected),
    )
    return fake


def test_check_model_ok(
    fake_model_installed: FakeModel, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    assert main(["--check-model", "--config", str(tmp_path / "none.toml")]) == 0
    assert "一致しました（3 ファイル）" in capsys.readouterr().out


def test_check_model_tampered(
    fake_model_installed: FakeModel,
    no_real_model: Path,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    (no_real_model / "README").write_bytes(b"x")
    assert main(["--check-model", "--config", str(tmp_path / "none.toml")]) == 2
    assert "改ざんされているおそれ" in capsys.readouterr().err


def test_check_model_missing(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    assert main(["--check-model", "--config", str(tmp_path / "none.toml")]) == 2
    assert "モデルがないため" in capsys.readouterr().err


def test_main_without_model_starts_without_keywords(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    calls: list[object] = []
    monkeypatch.setattr(main_module.server, "serve", lambda *a, **kw: calls.append(kw))
    monkeypatch.chdir(tmp_path)
    assert main([]) == 0
    assert len(calls) == 1
    assert keywords.MISSING_MODEL_MESSAGE in capsys.readouterr().out


def test_main_disabled_keywords_says_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.setattr(main_module.server, "serve", lambda *a, **kw: None)
    config = write_config(tmp_path, "[keywords]\nenabled = false\n")
    assert main(["--config", str(config)]) == 0
    assert "モデルがない" not in capsys.readouterr().out


def test_main_tampered_model_does_not_start(
    fake_model_installed: FakeModel,
    no_real_model: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_audio: FakeBackend,
    tmp_path: Path,
) -> None:
    calls: list[object] = []
    monkeypatch.setattr(main_module.server, "serve", lambda *a, **kw: calls.append(kw))
    (no_real_model / "am" / "final.mdl").write_bytes(b"x")
    assert main(["--config", str(tmp_path / "none.toml")]) == 2
    assert calls == []
    assert fake_audio.streams == []  # マイクも開かない


def test_main_demo_does_not_use_keywords(
    monkeypatch: pytest.MonkeyPatch, fake_audio: FakeBackend, tmp_path: Path
) -> None:
    def fail(*_: object, **__: object) -> None:
        raise AssertionError("デモでは音声認識を使わない")

    monkeypatch.setattr(keywords, "prepare_keywords", fail)
    monkeypatch.setattr(main_module.server, "serve", lambda *a, **kw: None)
    monkeypatch.chdir(tmp_path)
    assert main(["--demo"]) == 0
    assert fake_audio.streams == []


def test_test_keywords_without_model_exits_2(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    assert main(["--test-keywords", "--config", str(tmp_path / "none.toml")]) == 2
    assert "--test-keywords は使えません" in capsys.readouterr().err


def test_test_keywords_prints_only_kind(
    fake_model_installed: FakeModel,
    fake_audio: FakeBackend,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    printed: list[str] = []

    def fake_print(*args: object, **_: object) -> None:
        printed.append(" ".join(str(a) for a in args))
        if re.fullmatch(r"death \(-?\d+ ms\)", printed[-1]):
            raise KeyboardInterrupt  # 1 つ検知したら Ctrl+C の代わりに止める

    def start(self: FakeStream) -> None:
        self.started = True
        # 話して (2 ブロック)、黙る (話し終わりになるまで)
        for _ in range(2):
            self.push(block())
        for _ in range(12):
            self.push(block(0.0))

    monkeypatch.setattr(main_module, "print", fake_print, raising=False)
    monkeypatch.setattr(FakeStream, "start", start)
    assert main(["--test-keywords", "--config", str(tmp_path / "none.toml")]) == 0
    assert any(line.startswith("death (") for line in printed)
    # 認識した文字列は表示しない
    assert not any("死ん" in line for line in printed)
    assert fake_audio.streams[0].closed


# --test-keywords の時間の表示 (偽の時計の時刻を渡す)


def test_reaction_after_speech_ended_is_positive() -> None:
    timer = main_module.ReactionTimer()
    assert timer.speech(speaking=True, now_ms=1_000) == []
    assert timer.speech(speaking=False, now_ms=2_000) == []
    assert timer.keyword("clear", 2_250) == ["clear (250 ms)"]


def test_reaction_before_speech_ended_waits_and_is_negative() -> None:
    timer = main_module.ReactionTimer()
    timer.speech(speaking=True, now_ms=1_000)
    # 話している間に (部分結果で) 検知したら、話し終わるまで表示を待つ
    assert timer.keyword("clear", 1_880) == []
    assert timer.speech(speaking=False, now_ms=2_000) == ["clear (-120 ms)"]
    # 表示したものは次の話し終わりでは出さない
    timer.speech(speaking=True, now_ms=3_000)
    assert timer.speech(speaking=False, now_ms=4_000) == []


def test_reaction_counts_from_latest_speech_end() -> None:
    timer = main_module.ReactionTimer()
    timer.speech(speaking=True, now_ms=0)
    timer.speech(speaking=False, now_ms=1_000)
    timer.speech(speaking=True, now_ms=2_000)
    timer.speech(speaking=False, now_ms=3_000)
    assert timer.keyword("death", 3_400) == ["death (400 ms)"]


def test_reaction_without_speech_end() -> None:
    # 音量が発話のしきい値に届かず、話し終わりを検出していないとき
    timer = main_module.ReactionTimer()
    assert timer.keyword("death", 500) == ["death (話し終わりを検出していません)"]


# プライバシー (文字列・構文の検査)


def test_keywords_opens_files_only_to_hash() -> None:
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    opens: list[tuple[str, ast.Call]] = []
    for func in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        for node in ast.walk(func):
            if isinstance(node, ast.Call):
                name = getattr(node.func, "attr", getattr(node.func, "id", ""))
                if name in {"open", "write_text", "write_bytes", "mkdir", "unlink"}:
                    opens.append((func.name, node))
    assert [name for name, _ in opens] == ["_sha256"]
    _, call = opens[0]
    assert [a.value for a in call.args if isinstance(a, ast.Constant)] == ["rb"]


def test_keywords_does_not_print_or_log() -> None:
    text = SRC.read_text(encoding="utf-8")
    tree = ast.parse(text)
    calls = {
        getattr(n.func, "id", getattr(n.func, "attr", ""))
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
    }
    assert "print" not in calls
    assert "logging" not in text
    assert "logger" not in text


def test_vosk_is_given_model_path() -> None:
    # model_path を渡さないと、Vosk はネットからモデルを取得しようとする
    text = SRC.read_text(encoding="utf-8")
    assert 'vosk.Model(model_path=".")' in text
    assert "model_name" not in text
    assert "eval(" not in text
