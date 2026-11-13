# タスク：アプリのアイコン

- ID：T-20
- Phase：v1.1.0
- 関連要件：NFR-03、配布形式（exe）、メンダコのデザインの決定事項
- ブランチ名：`feat/app-icon`

## 目的

`stream-buddy.exe` にメンダコのアイコンを付け、エクスプローラー・タスクバー・デスクトップのショートカットでメンダコの顔が見えるようにする。

## 読む設計書

- `CLAUDE.md`
- `src/stream_buddy/overlay/index.html`、`static/style.css`、`static/img/mendako-body.png`
- `scripts/build_exe.py`
- `assets/LICENSE`、`CREDITS.md`

## 追加してよい依存

- **ビルド用の `build` グループに `pillow` を追加してよい**（PyInstaller が PNG から ICO を作るとき、または ICO を作るスクリプトで使う）
- 本体の `dependencies` と `dev` グループには入れない

## 仕様

### アイコンの絵

- **Normal の表情**のメンダコ（体の画像 ＋ SVG の目と口、口は閉じた状態）
- 背景は透明。正方形の中央に配置し、余白は少なめ（小さいサイズでも大きく見えるように）
- テンションの色の変化（光・暖色など）はかけない

### 作り方

- `scripts/make_icon.py`（新規）を作る
  - 入力：体の画像と、ページで使っている顔の SVG の部品（同じ見た目になること）
  - 出力：`assets/icon/stream-buddy.ico`（16・24・32・48・64・128・256 px を含む）と、確認用の `assets/icon/stream-buddy-256.png`
  - 顔の描き方は、ページと**同じ見た目**になれば方法は問わない（ヘッドレスのブラウザでページの SVG を描いて切り出す、Pillow で描く、など）。選んだ方法と理由を報告する
- **16・24・32 px でも、メンダコの形と目がわかること**
  - 小さいサイズで目がつぶれるなら、そのサイズだけ目を少し大きくする・輪郭を太くするなどの調整をしてよい（調整したら報告する）
- 作った `.ico` と `.png` はリポジトリにコミットする（ビルドのたびには作らない。絵を変えたときだけ `make_icon.py` を実行する）
- `make_icon.py` は、外部と通信しない

### exe への付け方

- `scripts/build_exe.py` で、PyInstaller に `assets/icon/stream-buddy.ico` を指定する
- アイコンのファイルがないときは、ビルドを失敗させる

### ライセンスとクレジット

- アイコンは体の画像から作るので、同じ **CC BY 4.0** とする
- `assets/LICENSE` の対象に `assets/icon/` を加える文案を報告する（`assets/LICENSE` は AI が変更できない設定のため、人が直す）
- `CREDITS.md` にアイコンの項目を加える（体の画像から作成、顔は SVG）

## テスト

- `assets/icon/stream-buddy.ico` があり、16・24・32・48・64・128・256 px をすべて含む（ICO のヘッダーを標準ライブラリで読んで確かめる）
- 各サイズの画像に透明な部分がある
- `build_exe.py` が `--icon` に `assets/icon/stream-buddy.ico` を渡す。ファイルがないとビルドを失敗させる
- `CREDITS.md` にアイコンの項目がある
- `make_icon.py` に、ネットワークに関わる import（`urllib`、`http`、`socket`、`requests` など）がない

## やること

1. `feat/app-icon` ブランチを **`origin/main` から**作る
2. `build` グループに `pillow` を追加する（必要な場合）
3. `make_icon.py` を作り、アイコンを作る
4. 16・32・256 px を画像で確かめ、見え方を報告する
5. `build_exe.py` を直し、exe をビルドして、エクスプローラーでアイコンが付いていることを確かめる（できる範囲で。できなければ人の確認に回す）
6. `docs/build.md`（アイコンの作り直し方）、`docs/status.md` を更新する

## 手動確認（人が行う）

- エクスプローラーで `stream-buddy.exe` にメンダコのアイコンが付いている（表示を「大アイコン」「詳細」などに変えて確かめる）
- 起動中、タスクバーにメンダコのアイコンが出る
- デスクトップにショートカットを作ると、メンダコのアイコンになる

## やらないこと

- OBS のページのファビコン（OBS では表示されないため）
- インストーラー、スタートメニューへの登録
- バージョン情報（ファイルのプロパティの「詳細」）の埋め込み

## 変更してよいファイル

- `scripts/make_icon.py`（新規）、`scripts/build_exe.py`
- `assets/icon/`（新規）
- `pyproject.toml`、`uv.lock`（`build` グループへの `pillow` の追加のみ）
- `CREDITS.md`
- `tests/` 配下（このタスクに関係するもの）
- `docs/build.md`、`docs/status.md`
- `tasks/T-20-app-icon.md`（このファイル。コミットに含める）

## 完了条件

- [ ] 上記のテストがすべてあり、`uv run pytest` が通る
- [ ] `uv run ruff check .` / `uv run ruff format --check .` / `uv run mypy src` が通る
- [ ] `uv sync --locked`（`build` グループなし）が通り、本体の依存が増えていない
- [ ] 16・32・256 px のアイコンの見え方を報告した
- [ ] `git status` に「変更してよいファイル」以外の変更がない
- [ ] `feat/app-icon` ブランチでコミットした（push はしない）
- [ ] CLAUDE.md の形式で報告した
