# タスク：<短い名前>

- ID：T-<番号>
- Phase：<0〜4>
- 関連要件：<FR-xx / NFR-xx / SR-xx>
- ブランチ名：`feat/<内容>`

## 目的

<このタスクで何ができるようになるか、1〜2 文で>

## 読む設計書

- `docs/...`

## やること

1.
2.

## やらないこと

- <範囲外のこと。ついでの改善をさせないために明記する>

## 変更してよいファイル

- `src/stream_buddy/...`
- `tests/...`

## 完了条件

- [ ] <動作として確認できること>
- [ ] テストを追加し、`uv run pytest` が通る
- [ ] `uv run ruff check .` / `uv run ruff format --check .` / `uv run mypy src` が通る
- [ ] `docs/status.md` を更新した
- [ ] 作業ブランチでコミットした（push はしない）
