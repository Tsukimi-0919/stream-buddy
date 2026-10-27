# タスク：死亡とクリアの画面演出

- ID：T-15
- Phase：3
- 関連要件：FR-09（演出）、FR-03（OBS 表示）、NFR-03、SR-04
- ブランチ名：`feat/effects`

## 目的

`effect` メッセージ（`death` / `clear`）を受け取ったら、ページで画面演出を出す。
サーバー側はすでに `effect` を送っているので、**主にページ側の作業**になる。

## 読む設計書

- `CLAUDE.md`
- `docs/state-machine.md`（イベント：演出の長さ 3 秒）
- `docs/ws-protocol.md`（`effect`）
- `src/stream_buddy/overlay/`（`index.html`、`static/style.css`、`static/app.js`）
- `src/stream_buddy/state/constants.py`（演出の長さ）

## 追加してよい依存

なし。ページは素の HTML / CSS / JavaScript のまま。

## 仕様

### 演出の中身

| | 死亡（`death`） | クリア（`clear`） |
| --- | --- | --- |
| 画面 | ページ全体がゆっくり暗くなり（周りほど暗いビネット）、ゆっくり戻る | ページ全体に虹色のグラデーションがふわっと広がり、紙吹雪が上から舞う |
| メンダコ | 色があせ（灰色寄り）、少し下に沈み、しょんぼりした目（たれ目や涙）になる | 大きく1回跳ねて、キラキラの目になる |
| 長さ | 3 秒（`constants.py` の演出の長さと同じ） | 3 秒 |

- 演出が終わったら、元の見た目（そのときのテンションの見た目）に戻る
- 演出中に次の `effect` が来たら、新しい演出を最初から出し直す
- 口パクと吹き出しは、演出中も動く（吹き出しは演出より手前に表示する）
- 背景が透過のとき（`display: transparent`）も、クロマキー（`chroma`）のときも、演出が見えること

### 光の点滅への配慮（必須）

配信を見る人の中には、光の点滅で体調を崩す人がいる。

- **1 秒間に 3 回より多く明るさが大きく変わる表現は使わない**（点滅・フラッシュ・ストロボを使わない）
- 暗くなる・明るくなる変化は、0.5 秒以上かけてゆっくり行う
- `prefers-reduced-motion` が有効なときは、紙吹雪・跳ねる・沈むなどの動きを出さず、**色の変化だけ**にする

### 置き場所（`&pos=`）

演出をページ全体に出せるよう、メンダコの位置を URL で選べるようにする。

- OBS の URL に `&pos=` を付けると、メンダコを置く場所を変えられる
  - `center`（既定。今までどおり）、`bottom-right`、`bottom-left`、`top-right`、`top-left`
  - 上記以外の値は無視して `center` にする
- ページはサーバーに新しい情報を送らない。URL を読むだけ
- README に、「画面全体に演出を出したいときは、ブラウザソースを配信画面と同じ大きさ（例：1920×1080）にして、`&pos=bottom-right` などでメンダコの位置を決める」と書く

### 作り方のルール（CSP と SR-04）

- インラインのスクリプト・`<style>` 要素・`style` 属性は使わない
- 紙吹雪の粒は、**HTML にあらかじめ用意した要素**（例：30 個）を、クラスと `:nth-child` で色・位置・タイミングを変えて動かす。JavaScript で要素を作らない
- 演出の切り替えは、`data-effect` 属性（またはクラス）の付け外しで行う
- 今までの禁止（`innerHTML` など）を守る

### 演出の長さをそろえる

- CSS の演出の長さ（3 秒）と、`constants.py` の演出の長さが一致していることを、テストで確かめる
- 長さは CSS のカスタムプロパティ（例：`--effect-duration: 3s`）1か所にまとめる

### デモ

- `--demo` の流れで、死亡とクリアの両方の演出が見られること（今の流れで見られれば `demo.py` は変えない）

## テスト（`tests/test_overlay.py` など）

- `style.css` に `death` と `clear` の演出の指定がある
- `style.css` の `--effect-duration` が `constants.py` の演出の長さと一致する
- 演出のアニメーションが無限に繰り返さない（`infinite` が演出の指定に含まれない）
- `prefers-reduced-motion` の中で、演出の動き（紙吹雪・跳ねる・沈む）が止められている
- 明るさを変えるアニメーションの長さが 0.5 秒以上（文字列から読み取って確かめる）
- `index.html` に紙吹雪の要素があり、インラインのスタイル・`style` 属性がない
- `app.js`：`effect` で `data-effect` を付け、3 秒で外す。新しい `effect` で出し直す。`pos` は決められた5つの値以外を無視する。禁止したものを使っていない
- `--demo` の流れで `effect` の `death` と `clear` がどちらも送られる

## やること

1. `feat/effects` ブランチを **`origin/main` から**作る
2. 上の仕様を実装し、テストを書く
3. `README.md` に `&pos=` の使い方と、ブラウザソースの大きさの説明を書く
4. `docs/status.md` を更新する
5. 手動確認の手順を報告に書く

## 手動確認（人が行う）

1. `uv run stream-buddy --demo` で、OBS のブラウザソース（400×400、`&pos` なし）で死亡とクリアの演出が出る
2. ブラウザソースを 1920×1080 にして `&pos=bottom-right` を付け、画面全体に演出が出て、メンダコが右下にいる
3. 透過とクロマキーの両方で演出が見える
4. Windows の「アニメーション効果」をオフにすると、動きがなくなり色の変化だけになる
5. 演出がまぶしすぎたり、チカチカしたりしない

## やらないこと

- 演出の効果音（音を出す機能は作らない）
- 本番のメンダコ画像への差し替え
- 配信ログ（T-16）
- サーバー・状態機械・プロトコルの変更

## 変更してよいファイル

- `src/stream_buddy/overlay/index.html`、`src/stream_buddy/overlay/static/style.css`、`src/stream_buddy/overlay/static/app.js`
- `src/stream_buddy/demo.py`（デモで演出が見られない場合のみ）
- `tests/` 配下（このタスクに関係するもの）
- `README.md`（`&pos=` とブラウザソースの大きさの説明のみ）、`docs/status.md`
- `tasks/T-15-effects.md`（このファイル。コミットに含める）

## 完了条件

- [ ] 上記のテストがすべてあり、`uv run pytest` が通る
- [ ] `uv run ruff check .` / `uv run ruff format --check .` / `uv run mypy src` が通る
- [ ] `git status` に「変更してよいファイル」以外の変更がない
- [ ] `feat/effects` ブランチでコミットした（push はしない）
- [ ] CLAUDE.md の形式で報告した
