# タスク：キーワード検知（Vosk）を本体に組み込む

- ID：T-10
- Phase：2
- 関連要件：FR-07（キーワード検知）、FR-11（設定）、SR-07（モデルの改ざん）、SR-08（依存の脆弱性）、NFR-01、NFR-06、プライバシー方針
- ブランチ名：`feat/keywords`

## 目的

T-06 で採用した Vosk で、「死んだ」「やったー」などのキーワードを聞き取り、`Keyword(kind)` を出せるようにする。
音声認識モデルは**ハッシュで改ざんを確かめてから**読み込み、音声は**今までどおり保存しない・外に送らない**。

## 読む設計書

- `CLAUDE.md`
- `docs/adr/0003-asr-engine.md`（決定、既定のキーワードとおとり、モデルの SHA-256）
- `docs/requirements.md`（FR-07、SR-07、プライバシー）、`docs/threat-model.md`
- `src/stream_buddy/audio.py`、`src/stream_buddy/detect.py`、`src/stream_buddy/config.py`
- `src/stream_buddy/state/events.py`（`Keyword`）
- `spikes/asr_compare.py`（Vosk の文法の作り方、おとりの判定。**参考にするだけで、本体からは import しない**）
- `scripts/build_exe.py`

## 依存

- `vosk` を **本体の `dependencies`** に移す（`spike-asr` グループからは外す）。CI の `pip-audit` の対象になる
- `spike-asr` グループには `faster-whisper` だけが残る（スパイクのスクリプトは引き続き動くこと）
- これ以外は追加しない

## プライバシー方針の見直し（このタスクで設計書も直す）

T-05 では「音声のサンプルはコールバックの外に持ち出さない」としていた。キーワード検知には音声そのものが必要なので、次のように**範囲を限って**持ち出せるようにする。

- コールバックから認識用のスレッドへ、**上限つきのキュー**（最大 1 秒分）で音声のブロックを渡す。いっぱいなら**捨てる**（ためない）
- 認識用のスレッドは、受け取ったブロックをすぐに Vosk に渡し、手元に残さない
- 音声も、認識した文字列も、**ファイル・ログ・コンソールに出さない**
- 認識した文字列から取り出すのは「どのキーワードか（`death` / `clear`）」だけ
- `docs/requirements.md` のプライバシー、`docs/threat-model.md`、`README.md` の「プライバシー」を、この内容に合わせて直す（「保存しない」「外に送らない」は変わらない）

## 仕様

### 設定（`config.py`、`config.example.toml`）

```toml
[keywords]
enabled = true
model_dir = ""      # 空なら <exe またはカレントフォルダ>/models/vosk-model-small-ja-0.22。指定するなら絶対パスのみ
death = ["死んだ", "やられた"]
clear = ["クリア", "やったー"]
decoys = ["やっぱり", "クリーム", "しんどい", "かったるい"]   # おとりの言葉（0〜20 個、各 1〜20 文字）
```

- 既定のキーワードを ADR 0003 の決定に合わせて変える（`勝った` は既定から外す）
- `decoys` を追加する。キーワードとおとりに同じ言葉があればエラー
- `docs/requirements.md` の FR-07 と設定の説明も合わせて直す

### モデルの確認（SR-07）

- ADR 0003 に記録したモデルの、**すべてのファイル**の相対パスと SHA-256 の一覧を `src/stream_buddy/data/vosk-model-small-ja-0.22.sha256` に置く
  - 一覧は、つきみの PC の `models/vosk-model-small-ja-0.22/` から作る。ADR 0003 に記録した5ファイルの値と一致することを確かめてから置く（一致しなければ作業を止めて報告）
- 読み込みの前に、モデルのフォルダを一覧と照合する
  - 一覧のファイルがない、ハッシュが違う、一覧にないファイルがある → **読み込まずにエラーで起動しない**（モデルが改ざんされているかもしれないため）
- `--check-model` オプション：照合だけを行い、結果を表示して終了する

### モデルがないとき

- `keywords.enabled = true` でモデルのフォルダがない → **キーワード検知なしで起動する**。コンソールに「モデルがないためキーワード検知は無効です。取得方法は README を参照」と表示する（ホットキーは使える）
- `keywords.enabled = false` → モデルを探さない

### 文法と判定（`src/stream_buddy/keywords.py`）

- キーワードとおとりを、Vosk の語彙（`graph/words.txt`）で表せる形にする
  - 語彙にそのままあればそのまま使う
  - なければ、語彙の単語の**最長一致で前から分割**して、空白でつないだ句にする（例：「死んだ」→「死ん だ」）
  - 分割できなければ、**どの設定のどの言葉か**を示してエラー（言葉そのものは出してよい。設定に書いた本人の言葉のため）
- 文法 = キーワードの句 ＋ おとりの句 ＋ `[unk]`
- Vosk の最終結果（`Result`）が出るたびに判定する
  - おとりの句が含まれていれば、検知なし
  - そうでなく、キーワードの句が含まれていれば `Keyword(kind)`
  - 複数の種類が含まれていたら、検知なし（どちらか決められないため）
- Vosk のログは止める（`SetLogLevel(-1)`）
- 文字列の扱いは、Vosk や外部の値を `eval` などで解釈しない（JSON は `json.loads` のみ）

### 組み立て

- 認識用のスレッドから `asyncio` のループへ、`call_soon_threadsafe` で `Keyword` を渡す
- `Brain` へのつなぎ込みは T-12。このタスクでは、`--test-keywords` オプションで起動すると、検知した**種類だけ**（`death` / `clear`）をコンソールに表示する（認識した文字列は出さない）
- `--demo` のときは、マイクも Vosk も使わない

### exe

- `scripts/build_exe.py` で、`vosk` の DLL とハッシュの一覧が同梱されるようにする（モデル本体は同梱しない）
- ビルドした exe で `--check-model` が動くことを確かめる

## テスト

本物のモデルとマイクは使わない（CI にないため）。Vosk を呼ぶ部分は差し替えられるようにする。

- 設定：既定のキーワードとおとり、キーワードとおとりの重複がエラー、`model_dir` の相対パスがエラー
- モデルの確認：一致で通る、ファイルがない・ハッシュ違い・余分なファイルでエラー（一時フォルダに小さな偽モデルを作って確かめる）
- 分割：語彙にある語はそのまま、ない語は最長一致の句に、分割できない語はエラー（偽の語彙で確かめる）
- 判定：キーワードで検知、おとりで検知なし、キーワードとおとりが両方で検知なし、2種類で検知なし、`[unk]` だけで検知なし
- キュー：いっぱいのときにブロックが捨てられ、たまり続けない
- `audio.py`・`keywords.py` が `wave`・`soundfile`・`open(`（ハッシュ確認のための読み込みは除く）を使ってファイルに書かない（文字列での検査を、今の実装に合わせて直す）
- `keywords.py` に `print` や `logging` で認識結果の文字列を出す処理がない

## やること

1. `feat/keywords` ブランチを作る
2. 依存を移す
3. ハッシュの一覧を作り、ADR 0003 の値と照合する
4. 設定、`keywords.py`、`audio.py` のキュー、`__main__.py` のオプション、ビルドスクリプトを変更する
5. テストを書く
6. 設計書（requirements・threat-model・architecture・README のプライバシー、FR-07）を直す
7. 手動確認の手順を報告に書く（`--check-model`、`--test-keywords` での読み上げ、「やっぱり」のおとりの効果の確認）
8. `docs/status.md` を更新する

## やらないこと

- `Brain` とのつなぎ込み、演出（T-12、Phase 3）
- ホットキー（T-11）
- モデルの自動ダウンロード（取得は人が公式サイトから行う）
- 認識した文字列のログ保存（Phase 3 の `include_speech_text` で扱う）

## 変更してよいファイル

- `pyproject.toml`、`uv.lock`（`vosk` の移動のみ）
- `src/stream_buddy/keywords.py`（新規）、`src/stream_buddy/data/vosk-model-small-ja-0.22.sha256`（新規）
- `src/stream_buddy/audio.py`、`src/stream_buddy/config.py`、`src/stream_buddy/__main__.py`
- `config.example.toml`、`README.md`（プライバシーとモデルの取得方法のみ）
- `scripts/build_exe.py`
- `tests/` 配下（このタスクに関係するもの）
- `docs/requirements.md`、`docs/threat-model.md`、`docs/architecture.md`、`docs/status.md`
- `tasks/T-10-keywords.md`（このファイル。コミットに含める）

## 完了条件

- [ ] 上記のテストがすべてあり、`uv run pytest` が通る
- [ ] `uv run ruff check .` / `uv run ruff format --check .` / `uv run mypy src` が通る
- [ ] `uv sync --locked` が通り、`vosk` が本体の依存に、`faster-whisper` が `spike-asr` にだけある
- [ ] ハッシュの一覧が ADR 0003 の5ファイルの値と一致している
- [ ] `uv run stream-buddy --check-model` が通る
- [ ] exe で `--check-model` が通る
- [ ] `git status` に「変更してよいファイル」以外の変更がない
- [ ] `feat/keywords` ブランチでコミットした（push はしない）
- [ ] CLAUDE.md の形式で報告した
