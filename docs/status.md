# 実装状況

> これは「今の姿」。目指す姿は [architecture.md](architecture.md) を参照。
> AI エージェントはタスク完了のたびにこのファイルを更新する。

## 現在のフェーズ

**Phase 1：実装中（T-02 完了）**

Phase 0（設計と守りの準備）は完了。

## できていること

- リポジトリの守り（pre-commit、Claude Code の禁止設定、CI、Dependabot）
- 設計書の初版（requirements / architecture / threat-model / ws-protocol 草案）
- T-01：プロジェクトの土台（uv、`src/` レイアウト、Python 3.12 固定、ruff / mypy / pytest の設定）
  - `stream-buddy --version` でバージョンを表示できる
  - dev グループは ruff・mypy・pytest のみ
- T-02：設定ファイルの読み込みと検証（`src/stream_buddy/config.py`）
  - 実行時の依存として `pydantic`（v2）を追加
  - `load_config(path)` が TOML を読み、型と範囲を検証した変更不可の `Config` を返す。ファイルがなければ既定値
  - 知らないキー・範囲外の値・F1〜F12 以外のホットキー・death と clear の重複・`log.enabled = true` で `output_dir` が空／相対パス・壊れた TOML は、日本語メッセージの `ConfigError` になる
  - host は設定に含めない（SR-01）。`log.output_dir` はエラーメッセージに値を出さない
  - 設定例は `config.example.toml`

## まだないもの

- 機能モジュール（server / audio など）
- 設定ファイルの場所の決定と `--config` 引数（サーバー起動のタスクで行う）
- ログ出力先フォルダの存在確認・書き込み時のパス確認（ログのタスクで行う）
- OBS 用のページ
- メンダコの画像

## 次にやること

- T-03
