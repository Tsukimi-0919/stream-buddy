# タスク：テンションの見える化

- ID：T-14
- Phase：2（調整）
- 関連要件：FR-04（テンション管理）、NFR-04（差し替えやすさ）、SR-04、プライバシー方針
- ブランチ名：`feat/tension-visibility`

## 目的

T-13 の確認で「テンションの上り下がりがわからない」とわかった。原因が
「見た目の差が小さい」のか「そもそも盛り上がり度が上がっていない」のかを区別できるように、次の2つを行う。

1. **確認用の表示**：今の盛り上がり度とテンションを、コンソールとページで確かめられるようにする
2. **見た目の差を大きくする**：Calm / Normal / High を、色・目・動きで一目でわかるようにする

**しきい値などの数値は、このタスクでは変えない**。表示を使って人が測ってから、別のタスクで決める。

## 読む設計書

- `CLAUDE.md`
- `docs/state-machine.md`（テンション）
- `src/stream_buddy/state/tension.py`、`src/stream_buddy/state/brain.py`、`src/stream_buddy/app.py`、`src/stream_buddy/__main__.py`
- `src/stream_buddy/overlay/`（`index.html`、`static/style.css`、`static/app.js`）

## 追加してよい依存

なし。

## 仕様

### 1. 状態の読み出し（`state/`）

- `Brain` に、今の状態を**読み出すだけ**のメソッド `snapshot(now_ms)` を追加する。返すもの：
  - 盛り上がり度（0〜100）と、その内訳（話していた割合による値、イベントの補正）
  - 今のテンション、前回テンションが変わってからの時間（ms）
  - 沈黙ハンターの状態と回数、イベントの状態
- **状態は変えない**（呼んでも呼ばなくても、`step` の結果が同じであること）。`state-machine.md` の遷移と数値は変えない

### 2. `--debug`（コンソールへの表示）

- `--debug` を付けて起動すると、**2 秒ごと**に1行、次の形で表示する

  ```
  [debug] 盛り上がり度 48（話した割合 48 + 補正 0） normal（12.4 秒前に変化） 沈黙: Waiting 0回 イベント: Ready
  ```

- テンションが変わったときは、その時点でも1行表示する（例：`[debug] テンション normal → high`）
- 表示してよいのは上の**数値と状態の名前だけ**。発話の内容、セリフの文字列、キーワードの文字列、トークン、ファイルのパスは出さない
- `--demo` とも一緒に使える
- `--debug` なしのときは、今までどおり何も出さない

### 3. ページでの確認用の表示（`?debug=1`）

- OBS の URL の末尾に `&debug=1` を付けると、ページの隅に小さく**今のテンションの名前**（`calm` / `normal` / `high`）を表示する
  - サーバーから新しいメッセージは送らない。ページが受け取った `tension` を表示するだけ
  - 表示は `textContent` で行う
  - `debug` がない、または `1` 以外なら表示しない
- 配信画面にこの表示が映らないよう、README に「確認が終わったら `&debug=1` を外す」と書く

### 4. 見た目の差を大きくする（`style.css`、`index.html`）

ページの `data-tension` 属性（またはクラス）で切り替える。インラインのスタイル・`style` 属性は使わない（CSP のため）。

| | Calm | Normal | High |
| --- | --- | --- | --- |
| 動き | ゆっくり大きくぷかぷか（周期 4 秒ほど） | 小さく上下（周期 2 秒ほど） | 大きく速く弾む（周期 0.6 秒ほど）、少し左右にも揺れる |
| 体の色 | 少し青みがかる・彩度を下げる | 元の色 | 暖色寄り・明るく、うっすら光る（`filter: drop-shadow` など） |
| 目 | 半目（まぶたを描く） | 普通 | キラキラ（星や光の形の要素を表示） |
| 切り替わり | 0.5 秒ほどでなめらかに変わる | | |

- 目の形は、SVG に要素を用意しておき、クラスで表示・非表示を切り替える（JavaScript で SVG を書き換えない）
- 口パク（`speech`）と吹き出しは、どのテンションでも今までどおり動くこと
- `prefers-reduced-motion` が有効なときは、動きを小さくする（色と目の変化は残す）
- メンダコは引き続き**オリジナルの仮の SVG**。既存のキャラクターに似せない

### 5. デモ

- `--demo` の流れで、Calm・Normal・High の3つがすべて見られることを確かめる（今の流れで見られない状態があれば、`demo.py` の流れを直す）

## テスト

- `snapshot`：内訳の合計が盛り上がり度と一致する、呼んでも状態が変わらない（`snapshot` を挟んだ場合と挟まない場合で `step` の出力が同じ）
- `--debug`：2 秒ごとに表示される、テンションの変化で表示される、表示にセリフ・キーワード・トークン・パスの文字列が含まれない（偽の時計と偽の入力で確かめる）
- `--debug` なしでは `[debug]` の行が出ない
- ページ：`index.html` と `style.css` にインラインのスタイルや `style` 属性がない、`app.js` が `debug` の表示に `textContent` だけを使い、禁止したもの（`innerHTML` など）を使っていない（今までの検査を通る）
- `style.css` に `calm`・`normal`・`high` それぞれの見た目の指定があり、`prefers-reduced-motion` の指定がある（文字列で確かめる）
- `--demo` の流れで、`tension` の `calm`・`normal`・`high` がすべて送られる

## やること

1. `feat/tension-visibility` ブランチを **`origin/main` から**作る
2. 上の仕様を実装し、テストを書く
3. `README.md` に `--debug` と `&debug=1` の使い方と注意を書く
4. `docs/status.md` を更新する
5. 手動確認の手順を報告に書く（下の「人が行う測定」を含める）

## 人が行う測定（このタスクのあとで行う）

1. `uv run stream-buddy --demo --debug` で、OBS の見た目が Calm・Normal・High で一目でわかるか確かめる
2. `uv run stream-buddy --debug` で、**いつもの配信のように 5 分ほどゲームをしながら話す**
3. コンソールの盛り上がり度を見て、次を記録する
   - 普段話しているときの盛り上がり度のだいたいの範囲
   - 盛り上がったときの最大
   - Normal と High に何回なったか
4. その結果で、しきい値を変えるかを決める（別のタスク）

## やらないこと

- しきい値・窓の長さ・補正などの数値の変更
- 本番のメンダコ画像への差し替え
- 死亡・クリアの画面演出（Phase 3）
- 盛り上がり度をページに送る、ファイルに保存する

## 変更してよいファイル

- `src/stream_buddy/state/brain.py`（`snapshot` の追加のみ）、必要なら各状態機械に読み出し用のプロパティを追加（**動きは変えない**）
- `src/stream_buddy/app.py`、`src/stream_buddy/__main__.py`、`src/stream_buddy/demo.py`
- `src/stream_buddy/overlay/index.html`、`src/stream_buddy/overlay/static/style.css`、`src/stream_buddy/overlay/static/app.js`
- `tests/` 配下（このタスクに関係するもの）
- `README.md`（`--debug` と `&debug=1` の説明のみ）、`docs/status.md`
- `tasks/T-14-tension-visibility.md`（このファイル。コミットに含める）

## 完了条件

- [ ] 上記のテストがすべてあり、`uv run pytest` が通る
- [ ] `uv run ruff check .` / `uv run ruff format --check .` / `uv run mypy src` が通る
- [ ] `docs/state-machine.md` の照合テストを含め、既存の状態機械のテストがすべて変わらず通る
- [ ] `git status` に「変更してよいファイル」以外の変更がない
- [ ] `feat/tension-visibility` ブランチでコミットした（push はしない）
- [ ] CLAUDE.md の形式で報告した
