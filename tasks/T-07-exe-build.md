# タスク：PyInstaller での exe 化の試作

- ID：T-07
- Phase：1
- 関連要件：配布形式の決定事項（exe・PyInstaller・必要なら Nuitka に切り替え）、SR-11（配布物の改ざん）、NFR-06（オフライン動作）
- ブランチ名：`feat/exe-build`

## 目的

stream-buddy を PyInstaller で exe にし、**Python を入れていない PC でも動く形**にできるかを確かめる。
あわせて、Windows Defender の誤検知が起きにくい形（1ファイル／フォルダ）を決めるための材料を集める。
ビルド手順は**1つのスクリプトに閉じ込め**、後で Nuitka に切り替えるときもそこだけ直せばよいようにする。

## 読む設計書

- `CLAUDE.md`
- `docs/requirements.md`（決定事項の「配布形式」「コード署名」、SR-11）
- `docs/threat-model.md`（SR-11）
- `src/stream_buddy/__main__.py`、`src/stream_buddy/server.py`（ページの読み込み方）、`src/stream_buddy/audio.py`

## 追加してよい依存

- `pyinstaller` を **`build` という新しい依存グループ**に入れる（`uv add --group build pyinstaller`）
  - 本体の `dependencies` と `dev` グループには入れない
- これ以外は追加しない

## 仕様

### ビルドスクリプト（`scripts/build_exe.py`）

- `uv run --group build python scripts/build_exe.py --mode onedir` または `--mode onefile` で動く
- 中で PyInstaller を呼ぶ（`subprocess` は `shell=False`、引数はリストで渡す）。PyInstaller の設定はスクリプトの中か、リポジトリに置く `.spec` ファイルにまとめる
- 出力先は `dist/`（`.gitignore` 済み）。ビルドの前に、前回の `build/` と `dist/` の中の stream-buddy 関係だけを消す
- exe の名前は `stream-buddy.exe`。コンソールのウィンドウは**表示する**（OBS の URL を表示するため）
- **UPX による圧縮は使わない**（誤検知が増えやすいため）
- 含めるもの：
  - OBS 用のページ（`src/stream_buddy/overlay/` 一式）
  - `sounddevice` が使う PortAudio の DLL
  - `config.example.toml`（exe と同じ場所に置く）
- 含めないもの：音声認識モデル、`spike-asr` の依存、テスト、`.env` など
- ビルドが終わったら、次を表示する
  - 出力の場所
  - exe（onedir の場合はフォルダ全体）の合計サイズ
  - `stream-buddy.exe` の SHA-256（SR-11）
- ビルドした exe で `--version` を実行し、`0.1.0` が出ることを確かめる（出なければ失敗として終了コード 1）

### 本体の修正（必要な場合のみ）

- exe の中でも OBS 用のページを見つけられるようにする。`__file__` からの相対パスで見つからない場合は、`importlib.resources` を使うか、PyInstaller の展開先に対応する。**どの方法にしたかを報告に書く**
- 設定ファイルの既定の場所（カレントフォルダの `config.toml`）は変えない。exe をダブルクリックで起動したときにどこを見るかを報告に書く

### 確認の手順書（`docs/build.md`）

人間が試作を確認するための手順を書く。

1. ビルド（onedir と onefile の両方）
2. 動作確認：`--version`、`--list-devices`、`--demo` で起動して OBS で表示、`--demo` なしで口パク
3. **Python を使わずに動くかの確認**：`dist` の中身だけを別のフォルダ（例：デスクトップ）にコピーして、そこから起動する
4. Windows Defender の確認：
   - `Start-MpScan -ScanType CustomScan -ScanPath <exe のフォルダ>` で手動スキャンし、結果を `Get-MpThreatDetection` で見る
   - スキャン後に exe を起動して、ブロックされないか
5. 記録すること：onedir と onefile それぞれの、サイズ・SHA-256・起動から URL 表示までの時間・Defender の結果

### ADR のひな形（`docs/adr/0004-exe-packaging.md`）

- 状態は「提案中」
- 比較の観点（Defender の結果、起動時間、サイズ、配りやすさ）と、結果の表の枠だけを作る。数字は人間の確認の後に書く
- 「署名しないことによる SmartScreen の警告」と、その説明を README に書くことは、ここでは決定済みとして記載する

## やること

1. `feat/exe-build` ブランチを作る
2. `build` グループに `pyinstaller` を追加する
3. `scripts/build_exe.py`（と、使う場合は `.spec`）を作る
4. 必要なら本体を修正し、そのテストを追加する
5. onedir と onefile の両方をビルドし、`--version` が通ることを確かめる（Defender のスキャンと OBS での確認は人間が行う）
6. `docs/build.md`、`docs/adr/0004-exe-packaging.md` を作る
7. `docs/status.md` を更新する

## やらないこと

- GitHub Actions でのビルドとリリースの仕組み（`.github/` は AI が変更しない決まりのため、人間が別途追加する）
- Nuitka の試作（PyInstaller で問題が出た場合に別のタスクで行う）
- Vosk と音声認識モデルの同梱（キーワード検知を組み込むタスクで扱う）
- コード署名、インストーラーの作成
- exe のアイコンやバージョン情報の埋め込み（Phase 4）

## 変更してよいファイル

- `pyproject.toml`、`uv.lock`（`build` グループの追加のみ）
- `scripts/build_exe.py`（新規）、`stream-buddy.spec`（使う場合のみ・新規）
- `src/stream_buddy/` 配下（exe でページを見つけるための修正が必要な場合のみ）
- `tests/` 配下（上記の修正に対するテストのみ）
- `docs/build.md`、`docs/adr/0004-exe-packaging.md`（新規）
- `docs/status.md`
- `tasks/T-07-exe-build.md`（このファイル。コミットに含める）

## 完了条件

- [x] `uv sync --locked`（`build` グループなし）が通り、本体の依存が増えていない
- [x] `uv run ruff check .` / `uv run ruff format --check .` / `uv run mypy src` / `uv run pytest` が通る
- [x] onedir と onefile の両方でビルドでき、どちらも `stream-buddy.exe --version` で `0.1.0` が出る
- [x] ビルド後にサイズと SHA-256 が表示される
- [x] `dist/` と `build/` が `git status` に出てこない
- [x] `docs/build.md` の手順で、人間が確認を始められる
- [x] `git status` に「変更してよいファイル」以外の変更がない
- [x] `feat/exe-build` ブランチでコミットした（push はしない）
- [x] CLAUDE.md の形式で報告した
