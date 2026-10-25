# タスク：プロジェクトの土台を作る

- ID：T-01
- Phase：1
- 関連要件：NFR-05（保守性）、SR-08（依存の固定）
- ブランチ名：`feat/project-skeleton`

## 目的

uv で管理される Python パッケージの土台を作り、品質チェック（ruff・mypy・pytest）が
ローカルと CI の両方で動く状態にする。以降のタスクはこの土台の上に機能を足していく。

## 読む設計書

- `CLAUDE.md`
- `docs/architecture.md`（「モジュールと責務」「技術選定」）
- `docs/status.md`

## やること

1. `feat/project-skeleton` ブランチを作る
2. uv でパッケージ構成のプロジェクトを作る
   - パッケージ名 `stream-buddy`、import 名 `stream_buddy`、`src/` レイアウト
   - Python は 3.12 に固定する（`.python-version` と `requires-python = ">=3.12,<3.13"`）
3. 開発用の依存を dev グループに追加する（このタスクで追加してよいのは次の3つだけ）
   - `ruff`、`mypy`、`pytest`
4. `pyproject.toml` にツールの設定を書く
   - ruff：`line-length = 100`、`target-version = "py312"`
     - `select = ["E", "F", "W", "I", "B", "UP", "S", "SIM", "RUF"]`（`S` は bandit 相当のセキュリティ検査）
     - `tests/` では `S101`（assert）を除外する
   - mypy：`strict = true`、`files = ["src"]`
   - pytest：`testpaths = ["tests"]`
5. 最小限のコードを置く
   - `src/stream_buddy/__init__.py`：`__version__ = "0.1.0"`
   - `src/stream_buddy/__main__.py`：`--version` を受け取るとバージョンを表示して終了する（標準ライブラリの `argparse` のみ使用）
   - `pyproject.toml` の `[project.scripts]` に `stream-buddy = "stream_buddy.__main__:main"` を登録する
6. テストを書く
   - `tests/test_version.py`：`__version__` が `pyproject.toml` のバージョンと一致すること、`main(["--version"])` がバージョンを出力すること
7. `uv.lock` を生成し、コミットに含める
8. `docs/status.md` を更新する（Phase 0 完了、T-01 完了、次は T-02）

## やらないこと

- 実行時の依存ライブラリの追加（FastAPI、音声関連など）。T-02 以降で個別に許可を得る
- `config`・`server`・`audio` など機能モジュールの作成（空のファイルも作らない）
- `README.md` の変更
- `CLAUDE.md` の禁止ファイル（`.gitignore`、`.github/`、`.claude/` など）の変更

## 変更してよいファイル

- `pyproject.toml`、`uv.lock`、`.python-version`（新規）
- `src/stream_buddy/__init__.py`、`src/stream_buddy/__main__.py`（新規）
- `tests/test_version.py`（新規）
- `docs/status.md`
- `tasks/T-01-project-skeleton.md`（このファイル。コミットに含める）

`uv init` が `README.md` や `.gitignore` など上記以外のファイルを作ったり変えたりした場合は、元に戻すこと。

## 完了条件

- [ ] `uv sync --locked` がエラーなく終わる
- [ ] `uv run stream-buddy --version` で `0.1.0` が表示される
- [ ] `uv run ruff check .` が通る
- [ ] `uv run ruff format --check .` が通る
- [ ] `uv run mypy src` が通る
- [ ] `uv run pytest` が通る
- [ ] `git status` に上記「変更してよいファイル」以外の変更がない
- [ ] `feat/project-skeleton` ブランチでコミットした（push はしない）
- [ ] CLAUDE.md の形式で報告した
