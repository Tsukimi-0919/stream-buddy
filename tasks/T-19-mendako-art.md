# タスク：メンダコの絵の差し替え（体は画像、顔は SVG）

- ID：T-19
- Phase：4（v1.0.0）
- 関連要件：FR-03、NFR-03、NFR-04、SR-04、メンダコのデザインの決定事項
- ブランチ名：`feat/mendako-art`

## 目的

仮の SVG で描いていたメンダコの**体**を、AI で作った 2D 画像に差し替える。
**目と口は今の SVG の部品をそのまま使い**、体の画像の上に重ねる。表情・口パク・テンションの見た目・演出は今までどおり動くこと。

将来、体の画像を自作の 3D モデルのレンダリングに差し替えるときも、**画像ファイルを入れ替えて顔の位置を調整するだけ**で済む作りにする。

## 画像について

- ファイル：`src/stream_buddy/overlay/static/img/mendako-body.png`（**人が置く**）
  - 512×512 の PNG、背景は透明、顔のパーツは描かれていない
  - 作成：ChatGPT（OpenAI）の画像生成、2026-11-12
  - 加工：背景以外を完全に不透明にし、512×512 に縮小した
- 配布条件：**CC BY 4.0**、表記は「Tsukimi-0919」
- 既存のキャラクターに似せたものではない（プロンプトに既存の作品名・キャラクター名は使っていない）

## 読む設計書

- `CLAUDE.md`
- `docs/requirements.md`（メンダコのデザイン）
- `src/stream_buddy/overlay/index.html`、`static/style.css`、`static/app.js`
- `scripts/build_exe.py`（overlay が exe に同梱されること）
- `LICENSE`（**読むだけ**。「`assets/` の素材は別のライセンス、`assets/LICENSE` を参照」と書かれている）

## 追加してよい依存

なし。

## 仕様

### 1. 体の画像に差し替える（`index.html`、`style.css`）

- メンダコの SVG の中で、**体・ひれ・足など体を描いている図形**を、SVG の `<image href="static/img/mendako-body.png">` に置き換える
  - SVG の中に入れることで、今の拡大・縮小、テンションの動き、演出の変形がそのまま効くようにする
  - CSP（`img-src 'self'`）のまま表示できること。インラインのスタイルや `style` 属性は使わない
- テンションと演出の**色の変化**（Calm の青み、High の暖色と光、死亡の灰色）が、体の画像にも効くこと（CSS の `filter` を体の画像を含むグループにかける）
- 目・口・涙・キラキラなどの**顔の部品はそのまま**残し、体の画像の顔にあたる場所に収まるよう、**位置と大きさを調整する**
  - 顔の位置と大きさは、CSS のカスタムプロパティか SVG の `transform` の1か所にまとめ、画像を差し替えたときに直しやすくする
- 吹き出しの位置（しっぽ）が、新しい体の形に合うように調整する
- `alt` に相当する説明（`<title>` など）を「メンダコ」とする

### 2. 素材のライセンスとクレジット

- `assets/LICENSE`（新規）
  - 対象：`src/stream_buddy/overlay/static/img/` の画像
  - 条件：CC BY 4.0（https://creativecommons.org/licenses/by/4.0/）、表記は「Tsukimi-0919」
  - 「この画像は AI（ChatGPT の画像生成）で作成し、加工したもの。地域によっては著作権が認められない場合がある」と正直に書く
- `CREDITS.md`（新規）
  - `mendako-body.png`：ChatGPT（OpenAI）の画像生成で作成（2026-11-12）。背景以外の不透明化と 512×512 への縮小を行った。CC BY 4.0
  - 使っているフォントや効果音などほかの素材がないことも確かめ、あれば書く
- `README.md` のライセンスの節を、`assets/LICENSE` と `CREDITS.md` を案内する形に直す

### 3. exe への同梱

- `static/img/` が exe に入ることを確かめる（overlay 一式を同梱する今の設定で入るなら、ビルドスクリプトは変えない）

## テスト（`tests/test_overlay.py` など）

- `index.html` が `static/img/mendako-body.png` を参照し、そのファイルがある
- 画像が PNG で、透明な部分（アルファ）を持ち、512×512、300 KB 以下（Python の標準ライブラリだけで PNG のヘッダーを読んで確かめる。依存を増やさない）
- `/static/img/mendako-body.png` が `image/png` で返り、CSP などのヘッダーが付いている
- インラインのスタイル・`style` 属性・禁止したもの（`innerHTML` など）を使っていない（今までの検査が通る）
- テンション（calm / normal / high）と演出（death / clear）の見た目の指定が、体の画像を含む要素に効いている（文字列で確かめる）
- `assets/LICENSE` と `CREDITS.md` があり、`mendako-body.png` と `CC BY 4.0` が書かれている
- 古い体の図形（今の仮の SVG の体）が残っていない

## やること

1. `feat/mendako-art` ブランチを **`origin/main` から**作る
2. 画像が置かれていなければ、置き場所を報告して止まる（人が置く）
3. 上の仕様を実装し、テストを書く
4. ヘッドレスのブラウザで、Calm / Normal / High / 死亡 / クリアの見た目の画面写真を撮り、顔が体に収まっていることを確かめる（画面写真はコミットしない。報告で確認したことを書く）
5. `docs/requirements.md` の「メンダコのデザイン」を「体は AI で作った 2D 画像、顔は SVG」に直す
6. `docs/status.md` を更新する

## 手動確認（人が行う）

- `uv run stream-buddy --demo` で、OBS のメンダコが新しい絵になり、口パク・表情・テンションの見た目・演出がすべて動く
- 暗い背景と明るい背景の両方で、輪郭がきれいに見える
- 200px くらいの大きさでも見やすい

## やらないこと

- 顔も画像にすること（案2）
- バージョン番号の変更、リリース（別のタスク）
- `LICENSE` の変更（人が行う場合のみ）

## 変更してよいファイル

- `src/stream_buddy/overlay/index.html`、`static/style.css`、`static/app.js`（顔の位置の調整に必要な場合のみ）
- `assets/LICENSE`（新規）、`CREDITS.md`（新規）
- `README.md`（ライセンスの節のみ）
- `tests/` 配下（このタスクに関係するもの）
- `docs/requirements.md`（メンダコのデザインのみ）、`docs/status.md`
- `tasks/T-19-mendako-art.md`（このファイル。コミットに含める）

画像ファイル（`mendako-body.png`）は人が置き、人がコミットに含める。

## 完了条件

- [ ] 上記のテストがすべてあり、`uv run pytest` が通る
- [ ] `uv run ruff check .` / `uv run ruff format --check .` / `uv run mypy src` が通る
- [ ] 画面写真で、5つの見た目すべてで顔が体に収まっていることを確かめた
- [ ] `git status` に「変更してよいファイル」と画像以外の変更がない
- [ ] `feat/mendako-art` ブランチでコミットした（push はしない）
- [ ] CLAUDE.md の形式で報告した
