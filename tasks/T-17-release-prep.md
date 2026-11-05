# タスク：公開前の小さな仕上げ

- ID：T-17
- Phase：4
- 関連要件：FR-11（設定）、SR-11（配布物）、NFR-04
- ブランチ名：`chore/release-prep`

## 目的

別ユーザーでの試用（2026-11-05）で、次のことがわかった。公開の前に直す。

1. `--version` がいつも `0.1.0` なので、**古い exe と新しい exe を見分けられなかった**
2. `--help` の `--demo` の説明が、T-12 より前の作りのまま
3. exe を新しくしても `config.toml` は古いまま残り、**新しい exe とかみ合わなかった**

あわせて、「コメントの読み上げは作らない」「メンダコのセリフの読み上げは外部の読み上げ道具に渡す（v1.1）」という判断を ADR に残す。

## 読む設計書

- `CLAUDE.md`
- `docs/requirements.md`（やらないこと、決定事項）、`docs/adr/`（書き方）
- `scripts/build_exe.py`、`src/stream_buddy/__main__.py`、`src/stream_buddy/__init__.py`、`src/stream_buddy/config.py`
- `README.md`

## 追加してよい依存

なし。

## 仕様

### 1. `--version` にビルドの情報を出す

- 表示の形：
  - exe：`stream-buddy 0.1.0 (b12307a, 2026-11-05)`
  - ビルドしたときに、コミットしていない変更があれば：`stream-buddy 0.1.0 (b12307a+dirty, 2026-11-05)`
  - ソースから動かしたとき（`uv run`）：`stream-buddy 0.1.0 (dev)`
- ビルドの情報は、**ビルドのときに作って exe に同梱する**
  - `scripts/build_exe.py` が、`git rev-parse --short HEAD` と `git status --porcelain` でコミットと変更の有無を調べる（`subprocess` は `shell=False`、引数はリスト）
  - 結果を JSON（`{"commit": "...", "dirty": false, "date": "YYYY-MM-DD"}`）にして **`build/` の中**に書き、PyInstaller で `stream_buddy/data/build_info.json` として同梱する。`src/` の中には書かない（コミットに混ざらないように）
  - git が使えないときは、ビルドを失敗させる（どのコードから作ったかわからない exe を作らないため）
- 実行時は `importlib.resources` で読む。ないときは `dev` と出す。中身が想定の形でなければ `unknown` と出す（エラーで止めない）
- 実行時に `git` を呼ばない
- 日付は UTC ではなくビルドした PC のローカルの日付でよい

### 2. `--demo` の説明

- `--help` の `--demo` の説明を、今の作り（偽の入力を状態機械に入れ、本物のテンション・セリフ・演出を確かめる）に合わせて直す

### 3. 古い設定のときの案内

- 設定ファイルの検証エラーのうち、**知らないキー**と**必須の項目がない**ときのメッセージの最後に、「新しいバージョンの config.example.toml と見比べてください」と添える
- セリフ集（`lines.toml`）の同じ種類のエラーにも、「新しいバージョンの lines.toml と見比べてください」と添える
- `include_speech_text` の案内（T-16）は今のまま残す

### 4. README

- 「更新するとき」の節を作る
  1. 新しい zip を、**古いフォルダとは別の場所**に展開する
  2. 古いフォルダから `config.toml` と、自分のセリフ集（使っていれば）とモデルを移す
  3. 新しい `config.example.toml` と見比べて、増えた項目・なくなった項目を直す
  4. `stream-buddy.exe --version` で、新しいバージョンになったことを確かめる
- トークンは `%LOCALAPPDATA%` にあるので、更新しても OBS の URL は変わらないことを書く

### 5. ADR 0005（`docs/adr/0005-comment-reading.md`）

- 状態：採用、日付：2026-11-05
- 背景：配信で使ってみて、メンダコのセリフを読み上げたい、視聴者のコメントも読み上げたい、という要望が出た
- 決定：
  - **視聴者のコメントの読み上げは作らない**。コメント読み上げの既存の道具（わんコメ、棒読みちゃんなど）にまかせる
  - **メンダコのセリフの読み上げは v1.1 で作る**。PC の中で動く読み上げの道具（棒読みちゃんなど）に、ローカルの通信でセリフを渡す。コメントと同じ道具に渡すので、声が重ならない
- 理由：
  - コメントの読み上げには、配信サイトとの通信、API キーなどの秘密情報の保存、知らない人の文章を声で流すことへの対策（NG ワード・長さ・連投）が必要で、「外部と通信しない」「秘密情報を持たない」という今の設計の前提が変わる
  - 既存の道具は、これらの対策を長く作り込んでいる
  - メンダコのセリフは、配信者が書いたものだけなので、読み上げても内容の心配がない
- 結果：`docs/requirements.md` の「やらないこと」に「視聴者のコメントの読み上げ（ADR 0005）」を加える。v1.1 の読み上げの設計は別のタスクで行う

## テスト

- `--version`：ビルドの情報がないとき `(dev)`、あるとき `(コミット, 日付)`、`dirty` のとき `+dirty`、中身が壊れているとき `(unknown)`（偽の `build_info.json` で確かめる）
- ビルドスクリプト：ビルドの情報の JSON を作る関数を、偽の `git` の結果で確かめる。git が使えないときに失敗する
- 設定とセリフ集：知らないキー・必須の項目がないときのメッセージに、見比べる案内が入る。ほかのエラーには入らない
- `src/stream_buddy/` に `build_info.json` が置かれていない（コミットに混ざらない）

## やること

1. `chore/release-prep` ブランチを **`origin/main` から**作る
2. 上の仕様を実装し、テストを書く
3. exe をビルドして、`--version` にコミットと日付が出ることを確かめる
4. ADR 0005 を書き、`docs/requirements.md` の「やらないこと」を直す
5. `docs/status.md` を更新する

## やらないこと

- バージョン番号の変更（`0.1.0` のまま。公開のタスクで決める）
- 読み上げの機能（v1.1）
- GitHub Actions でのビルド（`.github/` は AI が変更しない決まり。人が別に追加する）

## 変更してよいファイル

- `scripts/build_exe.py`
- `src/stream_buddy/__main__.py`、`src/stream_buddy/__init__.py`、`src/stream_buddy/config.py`、`src/stream_buddy/lines.py`
- 必要なら `src/stream_buddy/build_info.py`（新規。読み込みだけを行う）
- `tests/` 配下（このタスクに関係するもの）
- `README.md`（「更新するとき」の節のみ）
- `docs/adr/0005-comment-reading.md`（新規）、`docs/requirements.md`（やらないことのみ）、`docs/status.md`
- `tasks/T-17-release-prep.md`（このファイル。コミットに含める）

## 完了条件

- [ ] 上記のテストがすべてあり、`uv run pytest` が通る
- [ ] `uv run ruff check .` / `uv run ruff format --check .` / `uv run mypy src` が通る
- [ ] ビルドした exe で `--version` にコミットと日付が出る
- [ ] `git status` に「変更してよいファイル」以外の変更がない（`build_info.json` が `src/` にない）
- [ ] `chore/release-prep` ブランチでコミットした（push はしない）
- [ ] CLAUDE.md の形式で報告した
