# タスク：テンションの反応を速くし、設定で変えられるようにする

- ID：T-23
- Phase：v1.2.0
- 関連要件：FR-04（テンション）、NFR-03、テンションの状態機械（ST-01〜ST-05）
- ブランチ名：`feat/tension-response`

## 目的

v1.1.0 を使ってみて、「テンションと実際の動きにラグがある」と感じた。
テンションが変わるまでの時間を短くし、配信者が自分の話し方に合わせて設定で調整できるようにする。

## 原因（調べた結果）

テンションは「直近 30 秒のうち話していた割合」（0〜100）で決まり、一度変わると 5 秒は変えない（`state/constants.py`）。
黙っている状態から話し続けたとき・話し続けたあと黙ったときの、変わるまでの時間（補正なし）は次のとおり。

| 動き | しきい値 | 窓 30 秒（今） | 窓 15 秒（案） |
| --- | --- | --- | --- |
| Calm → Normal | 35 以上 | 約 10.5 秒 | 約 5.3 秒 |
| Normal → High | 70 以上 | 約 21 秒 | 約 10.5 秒 |
| High → Normal | 50 未満 | 黙って約 15 秒 | 黙って約 7.5 秒 |
| Normal → Calm | 20 未満 | 黙って約 24 秒 | 黙って約 12 秒 |

口パクは話しているかどうかで**すぐ**動くので、遅れているのはテンション（動き・色・目）だけ。

## 読む設計書

- `CLAUDE.md`
- `docs/state-machine.md`（1. テンション）、`docs/requirements.md`（FR-04）
- `src/stream_buddy/state/constants.py`、`state/tension.py`、`state/brain.py`
- `src/stream_buddy/config.py`、`config.example.toml`
- `src/stream_buddy/app.py`（`Brain` を作るところ、`format_debug`）

## 追加してよい依存

なし。

## 仕様

### 1. 設定の項目を足す（`[tension]`）

```toml
[tension]
window_seconds = 15   # 5〜60。話していた割合を数える秒数。短いほど早く反応する
hold_seconds = 3      # 1〜10。テンションが変わったあと、次に変えない秒数
```

- `config.py` に `TensionConfig` を足し、範囲外はほかの項目と同じ形でエラーにする
- `config.example.toml` に、上の2行と説明を足す
- **既定値は `window_seconds = 15`、`hold_seconds = 3`**（仮。人が試して、リリース準備で決め直すことがある）
- `[tension]` がない古い `config.toml` でも、既定値で起動できること

### 2. 状態機械に渡す

- `TENSION_WINDOW_MS` と `TENSION_HOLD_MS` を、設定から渡せるようにする（`Brain` か `TensionMachine` の引数。既定値は定数のまま持ってよい）
- しきい値（35 / 20 / 70 / 50）、補正（±30、10 秒で 0 に戻る）、盛り上げのセリフの間隔（15 秒）は**変えない**
- 盛り上がり度は「窓の秒数のうち話していた割合」のまま。窓を変えても 0〜100 の範囲になること
- 純粋な状態機械のまま（時刻は引数で受け取る）にする

### 3. `--debug` の表示

- 起動時に `--debug` なら、使っている窓と待ちの秒数を1行出す（例：`[debug] テンション：窓 15 秒、変化のあと 3 秒は変えない`）

### 4. 設計書

- `docs/state-machine.md` の「1. テンション」の窓と待ちの値を、「設定で変えられる（既定 15 秒・3 秒）」に直し、決定の表に「2026-11-13 に 30 秒・5 秒から変更。v1.1.0 の試用でラグが気になったため」と書く
- 上の「原因」の表（窓 30 秒と 15 秒の比較）を、`docs/state-machine.md` に載せる
- README の設定の説明に `[tension]` を足す

## テスト

- 設定：既定値、範囲の端（5・60、1・10）、範囲外のエラー、`[tension]` がないときの既定値
- 状態機械（窓 15 秒・待ち 3 秒で）
  - 黙っている状態から話し続けると、約 5.3 秒で Normal、約 10.5 秒で High になる（100 ms 刻みで確かめてよい）
  - 話し続けたあと黙ると、約 7.5 秒で Normal に、そのあと約 12 秒で Calm になる
  - 変わったあと 3 秒は、しきい値をこえても変わらない
- 窓 30 秒・待ち 5 秒を渡すと、今までと同じ動きになる（今のテストを、その値を渡す形で残してよい）
- `--debug` で、窓と待ちの秒数の行が出る

## やること

1. `feat/tension-response` ブランチを **`origin/main` から**作る
2. テストを書き、上の仕様を実装する
3. `docs/state-machine.md`、`README.md`、`config.example.toml`、`docs/status.md` を更新する

## 手動確認（人が行う）

- `uv run stream-buddy --debug` で話してみて、テンションが変わる早さが自然か
- `config.toml` の `window_seconds` を 10・15・20 などに変えて試し、どれがいちばん合うか決める（結果はリリース準備で既定値に反映する）
- High から戻るのが早すぎて、ばたばた変わらないか

## やらないこと

- しきい値・補正・盛り上げのセリフの間隔の変更
- テンションの決め方そのものの変更（話した割合以外の要素を足す、など）
- ページ（`app.js`・`style.css`）の変更
- バージョン番号の変更、リリース

## 変更してよいファイル

- `src/stream_buddy/config.py`、`config.example.toml`
- `src/stream_buddy/state/constants.py`、`state/tension.py`、`state/brain.py`
- `src/stream_buddy/app.py`、`src/stream_buddy/__main__.py`（設定を渡すところと、`--debug` の1行のみ）
- `tests/` 配下（このタスクに関係するもの）
- `docs/state-machine.md`（1. テンションのみ）、`docs/status.md`
- `README.md`（設定の説明のみ）
- `tasks/T-23-tension-response.md`（このファイル。コミットに含める）

## 完了条件

- [ ] 上記のテストがすべてあり、`uv run pytest` が通る
- [ ] `uv run ruff check .` / `uv run ruff format --check .` / `uv run mypy src` が通る
- [ ] `git status` に「変更してよいファイル」以外の変更がない
- [ ] `feat/tension-response` ブランチでコミットした（push はしない）
- [ ] CLAUDE.md の形式で報告した
