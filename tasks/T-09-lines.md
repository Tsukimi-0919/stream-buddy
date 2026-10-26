# タスク：セリフ集の読み込みと選択

- ID：T-09
- Phase：2
- 関連要件：FR-06（セリフ選択）、NFR-04（差し替えやすさ）、SR-03・SR-04（`say` の形と表示）
- ブランチ名：`feat/lines`

## 目的

メンダコのセリフを TOML ファイルで持ち、場面とテンションに合わせて選べるようにする。
既定のセリフ集は exe に同梱し、配信者は自分のセリフ集に差し替えられる。

## 読む設計書

- `CLAUDE.md`
- `docs/state-machine.md`（「4. 出口（Arbiter）とセリフ」）
- `docs/ws-protocol.md`（`say` の `line_id` と `text` の制限）
- `src/stream_buddy/state/events.py`（`Say` の場面）、`src/stream_buddy/config.py`、`src/stream_buddy/protocol.py`
- `scripts/build_exe.py`（同梱するファイルの指定）

## 追加してよい依存

なし。TOML の読み込みは `tomllib`、乱数は `random.Random` を使う。

## 仕様

### 既定のセリフ集

- `src/stream_buddy/data/lines.toml`（このタスクと一緒に渡す。**中身の文言は変えない**）
- 場面の対応

| `Say` の場面 | ファイルの場所 | 備考 |
| --- | --- | --- |
| `silence` | `[silence]` の `calm` / `normal` / `high` | そのときのテンションで選ぶ |
| `high` | `[tension]` の `high` | |
| `death` | `[event]` の `death` | |
| `clear` | `[event]` の `clear` | |

### 検証（読み込み時に行い、違反があれば起動しない）

- 知らない表・キーがあればエラー。上の6つのリストはすべて必須
- 各リストは 1〜30 個の文字列
- 各セリフは 1〜80 文字（`say.text` の上限）。前後の空白だけのものは不可
- 改行・タブ・制御文字（Unicode の Cc・Cf のうち、絵文字に使うゼロ幅接合子 U+200D と異体字セレクタ U+FE0F は許可）は不可
- エラーは `ConfigError` と同じように、どのセリフが・なぜ違うかを日本語で示す（例：`[event] death の 3 番目が 81 文字です（上限 80 文字）`）。エラーメッセージにセリフ全文は出さず、何番目かで示す

### 自分のセリフ集への差し替え

- 設定に `[lines]` の表と `file` を追加する（`config.py`、`config.example.toml`）
  - 空文字なら既定のセリフ集を使う
  - 指定するときは**絶対パスのみ**（相対パスはエラー）
  - 指定したファイルが読めない・検証に失敗したら、既定にこっそり戻さず**エラーで起動しない**
- ファイルの読み込みは先頭 64 KB まで。それより大きければエラー

### 選び方（`src/stream_buddy/lines.py`）

- `LineBook`（読み込んだセリフ集）と `LinePicker`（選ぶ係）を作る
- `LinePicker.pick(situation, tension) -> (line_id, text)`
  - `line_id` は `"<表>.<キー>.<番号>"`（例：`event.death.2`）。`say.line_id` の制限（1〜64 文字）を満たす
  - 候補からランダムに選ぶが、**同じリストの直前に出したもの**は選ばない（候補が1つなら同じでよい）
  - 乱数は `random.Random` を外から渡せるようにする（テストで固定するため）
- 状態機械（`src/stream_buddy/state/`）は変更しない。`LinePicker` は T-12 の組み立てで出口のあとにつなぐ

### exe への同梱

- `scripts/build_exe.py` で `src/stream_buddy/data/` を同梱する
- 読み込みは `importlib.resources` を使い、exe の中でも見つかるようにする

## テスト（`tests/test_lines.py`）

- 既定のセリフ集が検証を通る。6つのリストがすべてある
- 既定のセリフ集のすべてのセリフが `protocol.py` の `say` として正しい（`line_id` と `text` の両方）
- 検証のエラー：知らないキー、リストの欠け、空のリスト、31 個、81 文字、空白だけ、改行、タブ、制御文字がそれぞれエラーになる
- 絵文字（🔥、🎉、ゼロ幅接合子を使う絵文字）は通る
- `[lines] file`：空なら既定、相対パスはエラー、存在しないファイルはエラー、壊れた TOML はエラー、64 KB を超えるとエラー
- 選び方：同じリストで2回続けて同じセリフにならない（多数回試す）、候補1つなら同じでよい、`silence` はテンションで選ぶリストが変わる、乱数を固定すると結果が決まる
- 文字数の数え方：80 文字ちょうどは通り、81 文字はエラー（`len()` で数える）

## やること

1. `feat/lines` ブランチを作る
2. 渡された `lines.toml` を `src/stream_buddy/data/` に置く
3. `lines.py` を作り、`config.py` と `config.example.toml` に `[lines]` を追加する
4. `scripts/build_exe.py` に同梱の指定を追加する
5. テストを書く
6. `docs/state-machine.md` の「セリフの選び方」の例（`[silence.calm]` など）を、実際のファイルの形に合わせて直す（今回に限り変更を許可する）
7. `docs/status.md` を更新する

## やらないこと

- セリフの文言の変更（文言の変更は人間が行う）
- 状態機械・サーバー・音声との組み立て（T-12）
- AI によるセリフ生成
- 設定画面

## 変更してよいファイル

- `src/stream_buddy/data/lines.toml`（新規。渡されたものをそのまま置く）
- `src/stream_buddy/lines.py`（新規）
- `src/stream_buddy/config.py`、`config.example.toml`（`[lines]` の追加のみ）
- `scripts/build_exe.py`（同梱の指定のみ）
- `tests/test_lines.py`（新規）、`tests/test_config.py`（`[lines]` の追加に伴うもののみ）
- `docs/state-machine.md`（「セリフの選び方」の例のみ）、`docs/status.md`
- `tasks/T-09-lines.md`（このファイル。コミットに含める）

## 完了条件

- [ ] 上記のテストがすべてあり、`uv run pytest` が通る
- [ ] `uv run ruff check .` / `uv run ruff format --check .` / `uv run mypy src` が通る
- [ ] `src/stream_buddy/data/lines.toml` の文言が、渡されたものと一致している
- [ ] `git status` に「変更してよいファイル」以外の変更がない
- [ ] `feat/lines` ブランチでコミットした（push はしない）
- [ ] CLAUDE.md の形式で報告した
