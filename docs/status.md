# 実装状況

> これは「今の姿」。目指す姿は [architecture.md](architecture.md) を参照。
> AI エージェントはタスク完了のたびにこのファイルを更新する。

## 現在のフェーズ

**Phase 0：設計と守りの準備**

## できていること

- リポジトリの守り（pre-commit、Claude Code の禁止設定、CI、Dependabot）
- 設計書の初版（requirements / architecture / threat-model / ws-protocol 草案）

## まだないもの

- Python のコード一式（`pyproject.toml` もまだない）
- OBS 用のページ
- メンダコの画像

## 次にやること

- Phase 0 のゲート確認（偽の秘密情報がコミット時に止まること）
- GitHub Actions のコミットハッシュ固定
- Phase 1 のタスク分割
