# タスク：OBS 用のページ（仮のメンダコ表示）

- ID：T-04
- Phase：1
- 関連要件：FR-02（口パクの表示側）、FR-03、FR-04（表示側）、FR-06（吹き出しの表示側）、SR-03、SR-04
- ブランチ名：`feat/overlay-page`

## 目的

OBS のブラウザソースで表示するページを作る。WebSocket でサーバーとつながり、
受け取ったメッセージどおりに「仮のメンダコ」を動かす。
音声入力はまだないので、確認用に**デモモード**も作り、配信画面での見え方を確かめられるようにする。

## 読む設計書

- `CLAUDE.md`
- `docs/ws-protocol.md`（ページ側のルール）
- `docs/threat-model.md`（SR-04）
- `src/stream_buddy/server.py`、`src/stream_buddy/protocol.py`

## 追加してよい依存

なし。ページは素の HTML / CSS / JavaScript で書き、npm などのパッケージは使わない。

## 仕様

### ファイル構成

- `src/stream_buddy/overlay/index.html`：本番のページ（T-03 の仮ページを置き換える）
- `src/stream_buddy/overlay/static/style.css`
- `src/stream_buddy/overlay/static/app.js`

### 仮のメンダコ

- `index.html` の中に、**オリジナルの簡単な SVG** で描く（丸い体、2つの目、口）。既存のキャラクターに似せない
- 口は「閉じた口」と「開いた口」の2つの要素を用意し、CSS のクラスで切り替える
- 本番の画像（AI で作る 2D 画像）への差し替えは後のタスクで行う。今回は仮でよい

### 接続（`app.js`）

- トークンはページの URL の `token` から取り出し、`ws://127.0.0.1:<ページと同じポート>/ws?token=<token>` に接続する
- 接続したら `hello` を1回送る（`page_version` は `"0.1.0"`）
- 切れたら再接続する。待ち時間は 1 秒から始めて倍々にし、上限 10 秒。つながったら 1 秒に戻す
- **トークンや URL を `console.log` などに出さない**

### 受け取ったメッセージの扱い

- JSON として読めない、`v` が 0 でない、知らない `type`、payload の形が違うものは**何もせずに無視**する
- `speech`：`speaking` が true なら口を開いたり閉じたりするアニメーション、false なら口を閉じる
- `tension`：`calm` はゆっくりぷかぷか、`normal` は小さく上下、`high` は大きく弾む（CSS アニメーション）
- `say`：吹き出しに `text` を表示し、5 秒後に消す。新しい `say` が来たら置き換える
- `display`：`transparent` は背景透過、`chroma` は背景を緑（`#00ff00`）にする
- `effect`：このタスクでは受け取っても何もしない（演出は Phase 3）

### 表示のルール（SR-04、CSP）

- 文字の表示は `textContent` だけを使う
- 次は**使わない**：`innerHTML`、`outerHTML`、`insertAdjacentHTML`、`document.write`、`eval`、`new Function`、文字列を渡す `setTimeout` / `setInterval`
- インラインのスクリプト（`<script>` の中身）、`<style>` 要素、`style` 属性は使わない（CSP で止められるため）。見た目の切り替えはクラスと `data-` 属性で行う
- ページの背景は既定で透過（`background: transparent`）

### サーバー側の変更

- ページから `hello` を受け取ったら、そのページにだけ現在の `display`（設定の `display.background`）を送る
- `--demo` オプションを追加する。指定すると、サーバーが次の流れを繰り返し `broadcast` する（各 2〜3 秒間隔）
  1. `tension: calm` → `speech: true` → `speech: false`
  2. `tension: normal` → `say: "ふむふむ、いい感じだね～"`
  3. `tension: high` → `speech: true` → `say: "うおおお！"` → `speech: false`
  - デモ用のセリフは `server.py` か専用のモジュールに定数として置く

## やること

1. `feat/overlay-page` ブランチを作る
2. 上記のページと静的ファイルを作る
3. サーバー側の変更（`hello` への `display` 返信、`--demo`）
4. テストを書く（JavaScript のテスト環境は入れず、Python から確認する）
   - `/overlay` の HTML に、`src` のない `<script>`、`<style>` 要素、`style` 属性がない
   - `app.js` に「使わない」に挙げたものが含まれていない（文字列で検査）
   - `app.js` に `console.log` などでトークンを出す処理がない（`console.` の呼び出し自体を禁止してよい）
   - `/static/app.js` と `/static/style.css` が正しい Content-Type で返り、CSP などのヘッダーが付いている
   - `hello` を送ると、設定どおりの `display` が届く
   - デモの流れのメッセージが、すべて `protocol.py` のモデルとして正しい
5. 手動確認の手順を報告に書く（ブラウザと OBS の両方）
6. `docs/status.md` を更新する

## やらないこと

- 音声入力、発話検知、テンションの計算（ページは受け取ったとおりに表示するだけ）
- 死亡・クリアの演出（Phase 3）
- 本番のメンダコ画像の作成や、画像ファイルへの差し替え
- サーバーの守り（Host・トークン・Origin・CSP）の変更

## 変更してよいファイル

- `src/stream_buddy/overlay/index.html`
- `src/stream_buddy/overlay/static/style.css`、`src/stream_buddy/overlay/static/app.js`（新規）
- `src/stream_buddy/server.py`、`src/stream_buddy/__main__.py`
- デモ用のモジュールを分ける場合は `src/stream_buddy/demo.py`（新規）
- `tests/test_overlay.py`（新規）、`tests/test_server.py`
- `docs/status.md`
- `tasks/T-04-overlay-page.md`（このファイル。コミットに含める）

## 完了条件

- [ ] 上記のテストがすべてあり、`uv run pytest` が通る
- [ ] `uv run ruff check .` / `uv run ruff format --check .` / `uv run mypy src` が通る
- [ ] `uv run stream-buddy --demo` で起動し、ブラウザで開くとメンダコが動き、吹き出しが出る
- [ ] サーバーを止めて再起動すると、ページが自動で再接続する
- [ ] `git status` に「変更してよいファイル」以外の変更がない
- [ ] `feat/overlay-page` ブランチでコミットした（push はしない）
- [ ] CLAUDE.md の形式で報告した
