# タスク：設定ファイルの読み込みと検証

- ID：T-02
- Phase：1
- 関連要件：FR-11（設定ファイル）、NFR-04（差し替えやすさ）、SR-01、SR-05、SR-06
- ブランチ名：`feat/config`

## 目的

TOML の設定ファイルを読み込み、型と値の範囲を検証した設定オブジェクトを返す `config` モジュールを作る。
間違った設定は起動時にわかりやすい日本語のエラーで止め、危険な値はそもそも書けないようにする。

## 読む設計書

- `CLAUDE.md`
- `docs/requirements.md`（FR-11、SR-01、SR-05、SR-06）
- `docs/architecture.md`（`config` の責務）

## 追加してよい依存

- `pydantic`（v2）：設定の検証に使う。T-03 以降の WebSocket メッセージの検証（SR-03）でも使う予定
  - `uv add pydantic` で追加する。これ以外の依存は追加しない
- TOML の読み込みは標準ライブラリの `tomllib` を使う

## 設定の仕様

ファイルは次の形。すべての項目に既定値があり、ファイルがなくても既定値で動く。

```toml
[server]
port = 8765                  # 1024〜65535

[audio]
device = ""                  # 空文字なら OS の既定のマイク。それ以外はデバイス名
speech_threshold_db = -40.0  # -80.0〜0.0。これより大きい音量を「発話中」とみなす

[silence]
seconds = 20                 # 5〜600。この秒数だけ発話がなければ沈黙ハンターが動く

[hotkeys]
death = "F9"                 # F1〜F12 のみ
clear = "F10"                # F1〜F12 のみ。death と同じキーは不可

[keywords]
death = ["死んだ", "やられた"]  # 各 1〜20 文字、最大 20 個
clear = ["勝った", "クリア"]    # 同上

[display]
background = "transparent"   # "transparent" または "chroma"

[log]
enabled = false              # true のときだけ配信ログを書く
output_dir = ""              # enabled = true のときは必須。絶対パスのみ
include_speech_text = false  # 発話テキストを残すか（プライバシーのため既定は false）
```

### 検証のルール

- 知らないキーがあればエラーにする（書き間違いに気づけるように。pydantic の `extra="forbid"`）
- 値の型・範囲が違えばエラーにする
- **待ち受けアドレス（host）は設定に含めない**。`127.0.0.1` 固定はサーバー側のコードで行う（SR-01）
- ホットキーは `F1`〜`F12` の文字列だけを受け付ける。修飾キーや他のキーは不可（SR-05）
- `log.enabled = true` かつ `output_dir` が空、または相対パスならエラー（SR-06）
  - このタスクではフォルダの存在確認まではしない。書き込み時のチェックはログのタスクで行う
- 設定オブジェクトは読み込み後に変更できない（`frozen=True`）

### エラーの出し方

- 独自の例外 `ConfigError` を作る
- メッセージは日本語で、どの項目がなぜ違うかがわかる形にする（例：`[server] port は 1024〜65535 の範囲で指定してください（指定値: 80）`）
- ファイルが TOML として壊れている場合も `ConfigError` にする
- エラーメッセージに、ファイルの中身全体や絶対パス以外の個人的な情報を含めない

## やること

1. `feat/config` ブランチを作る
2. `uv add pydantic`
3. `src/stream_buddy/config.py` を作る
   - 設定のモデル（上記の仕様どおり、セクションごとのモデル＋全体のモデル）
   - `load_config(path: Path | None) -> Config`：`None` またはファイルが存在しなければ既定値を返す
   - `ConfigError`
4. リポジトリ直下に `config.example.toml` を置く（上記の仕様の内容。コメントは日本語）
5. `tests/test_config.py` を書く。最低限、次を確認する
   - ファイルなし・`None` で既定値が返る
   - `config.example.toml` がそのまま読める
   - 範囲外の port、知らないキー、F13 のホットキー、death と clear が同じキー、`log.enabled = true` で `output_dir` が空または相対パス、壊れた TOML がそれぞれ `ConfigError` になる
   - 読み込んだ設定を書き換えようとするとエラーになる
6. `docs/status.md` を更新する

## やらないこと

- 設定ファイルの場所を探す処理、コマンドライン引数（`--config`）の追加（サーバー起動のタスクで行う）
- 設定ファイルへの書き込み、設定画面
- マイクの一覧取得やデバイス名の存在確認（音声のタスクで行う）
- ログの出力先フォルダの作成や存在確認

## 変更してよいファイル

- `pyproject.toml`、`uv.lock`（pydantic の追加のみ）
- `src/stream_buddy/config.py`（新規）
- `tests/test_config.py`（新規）
- `config.example.toml`（新規）
- `docs/status.md`
- `tasks/T-02-config.md`（このファイル。コミットに含める）

## 完了条件

- [ ] 上記のテストがすべてあり、`uv run pytest` が通る
- [ ] `uv run ruff check .` / `uv run ruff format --check .` / `uv run mypy src` が通る
- [ ] `uv sync --locked` が通る
- [ ] `git status` に「変更してよいファイル」以外の変更がない
- [ ] `feat/config` ブランチでコミットした（push はしない）
- [ ] CLAUDE.md の形式で報告した
