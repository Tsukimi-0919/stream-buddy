# 実装状況

> これは「今の姿」。目指す姿は [architecture.md](architecture.md) を参照。
> AI エージェントはタスク完了のたびにこのファイルを更新する。

## 現在のフェーズ

**Phase 1：実装開始（T-01 完了）**

Phase 0（設計と守りの準備）は完了。

## できていること

- リポジトリの守り（pre-commit、Claude Code の禁止設定、CI、Dependabot）
- 設計書の初版（requirements / architecture / threat-model / ws-protocol 草案）
- T-01：プロジェクトの土台（uv、`src/` レイアウト、Python 3.12 固定、ruff / mypy / pytest の設定）
  - `stream-buddy --version` でバージョンを表示できる
  - 実行時の依存はまだなし（dev グループは ruff・mypy・pytest のみ）

## まだないもの

- 機能モジュール（config / server / audio など）
- OBS 用のページ
- メンダコの画像

## 次にやること

- T-02
