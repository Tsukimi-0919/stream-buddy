# タスク：組み立て（入力 → 状態機械 → セリフ → OBS）

- ID：T-12
- Phase：2
- 関連要件：FR-02、FR-04〜FR-08、NFR-01、NFR-02、SR-01〜SR-05、プライバシー方針
- ブランチ名：`feat/assembly`

## 目的

これまでに作った部品を1つにつなぎ、`stream-buddy` を起動すれば、
**話すと口パクし、盛り上がると弾み、黙ると話しかけ、キーワードやホットキーで反応する**メンダコが OBS で動くようにする。
これで Phase 2 を完了させる。

## 読む設計書

- `CLAUDE.md`
- `docs/state-machine.md`（全体。特に「入力」「出力」と出口）
- `docs/architecture.md`（起動の流れ、既知の制約と回避策）
- `docs/ws-protocol.md`
- `src/stream_buddy/` のすべてのモジュール（`__main__.py`・`server.py`・`audio.py`・`detect.py`・`keywords.py`・`hotkey.py`・`lines.py`・`state/`・`demo.py`）

## 追加してよい依存

なし。

## 仕様

### 中心になる部品（`src/stream_buddy/app.py`）

- `asyncio` のループの中に、**入力のキュー（`asyncio.Queue`）を1つ**置き、すべての入力をそこに集める
  - 発話：`detect` の変化 → `SpeechStarted` / `SpeechEnded`
  - キーワード：`keywords` → `Keyword(kind)`
  - ホットキー：`hotkey` → `Hotkey(kind)`
  - 時計：100 ms ごとに `Tick`
  - スレッドからは今までどおり `call_soon_threadsafe` で入れる
- **キューから取り出して `Brain.step` を呼ぶのは、1つの処理（タスク）だけ**にする（状態機械を同時に触らないため）
- 時刻は `time.monotonic()` をミリ秒にしたものを、取り出したときに付ける。時計は差し替えられるようにする（テスト用）
- `Brain` の出力を WebSocket のメッセージに変えて `broadcast` する

| 出力 | 送るメッセージ |
| --- | --- |
| `Mouth(speaking)` | `speech` |
| `TensionChanged(level)` | `tension` |
| `Say(situation)` | `LinePicker.pick(situation, 今のテンション)` で選んだ `say` |
| `Effect(kind)` | `effect` |
| `TensionPeak` | 送らない（Phase 3 のログで使う。今は捨てる） |

- これまで `__main__.py` などが直接 `speech` を `broadcast` していた経路は廃止し、すべて `Brain` を通す
- `Brain` には `silence_seconds=config.silence.seconds` を渡す
- キューには上限を付ける（例：1000）。あふれたら入力を捨て、捨てた数だけを警告として数える（中身はログに出さない）

### ページが接続したとき

- `hello` を受け取ったら、そのページにだけ、今の `display` に加えて**今のテンション**も送る（再接続したページが今の状態から始められるように）

### 起動と終了の順番

起動（失敗したら、それまでに始めたものを片付けてから終わる）：

1. 設定を読み、検証する
2. セリフ集を読み、検証する
3. トークンを読む（なければ作る）
4. `keywords.enabled` ならモデルを確認して読み込む（**ほかのスレッドが動き出す前**。既知の制約のため）。モデルがなければキーワード検知なしで続ける
5. ホットキーを登録する。1つも登録できなくても**起動は続ける**（警告を出す）
6. サーバーを起動し、OBS の URL を表示する
7. マイクを開き、認識用のスレッドを始める
8. 時計と、キューを処理するタスクを始める

終了（Ctrl+C を含む）は逆の順番。どこかで例外が起きても、**マイクを閉じる・ホットキーの登録を外す・スレッドを止める**は必ず行う。

### `--demo`

- 今の「決まったメッセージを順に送る」作りをやめ、**偽の入力を `Brain` に入れる**形に変える。デモでも本物の状態機械とセリフ選びが動く
- マイク・Vosk・ホットキーは使わない
- 流れ（約 1 分で繰り返す）の例：
  1. 話す・止まるを繰り返して盛り上がり度を上げ、Normal → High にする
  2. `Hotkey(clear)` でクリアの演出とセリフ
  3. 話してから黙り、沈黙ハンターが話しかける（`silence.seconds` の設定を使う）
  4. `Keyword(death)` で死亡の演出とセリフ
- 流れは `demo.py` の定数にまとめる

### 守りとプライバシー

- これまでの守り（`127.0.0.1`、Host・トークン・Origin の確認、CSP、`RegisterHotKey` のみ、音声と認識結果を保存しない・表示しない）を**変えない**
- コンソールに出してよいのは、OBS の URL、起動・終了のお知らせ、警告だけ。発話の内容やセリフ選びの途中経過は出さない

## テスト（`tests/test_app.py`）

本物のマイク・Vosk・ホットキーは使わず、偽物と差し替えた時計で確かめる。

- 偽の発話 → `speech: true` / `speech: false` が届く
- 偽の発話を続けると、`tension` が `normal` → `high` と届き、`high` のセリフ（`say`）が届く
- 偽の `Hotkey(clear)` → `effect: clear` と、`[event] clear` のセリフが届く
- 偽の `Keyword(death)` → `effect: death` と、`[event] death` のセリフが届く。10 秒以内の2回目のキーワードは無視される
- 話し終わってから時計を `silence.seconds` 進めると、そのときのテンションの `silence` のセリフが届く
- 届いたメッセージは、すべて `protocol.py` のモデルとして正しい
- `hello` を送ると `display` と今の `tension` が届く
- キューがあふれても止まらず、捨てた数が数えられる
- 起動の途中（例：サーバーの起動）で例外が起きても、ホットキーの登録が外れ、マイクが閉じる
- 終了でスレッドとタスクがすべて止まる
- `--demo` の流れで、`effect`（`death` と `clear`）・`say`・`tension: high` がすべて1回以上届く（時計を進めて確かめる）
- 状態機械の外（`app.py`）で、`TensionPeak` 以外の出力が捨てられていない

## やること

1. `feat/assembly` ブランチを作る
2. `app.py` を作り、`__main__.py`・`server.py`・`demo.py` を組み替える
3. テストを書き、古い経路のテストを新しい形に直す
4. `docs/architecture.md` の「起動の流れ」と図を、実装に合わせて直す
5. `README.md` の「特長」から「（予定）」を外せるものは外す（演出は Phase 3 なので残す）
6. 手動確認の手順を報告に書く（下の「Phase 2 のゲート」）
7. `docs/status.md` を更新する

## Phase 2 のゲート（手動確認）

`uv run stream-buddy` で起動し、OBS で次を確かめる。

- 話すと口パクする
- しばらく話し続けると、動きが Normal → High に変わり、High のセリフが出る
- 黙って `silence.seconds` たつと話しかけてくる（設定で 5 秒などにすると確かめやすい）
- 「死んだ」「やったー」、ホットキーでセリフが出る
- サーバーを再起動しても、OBS がつながり直す
- exe でも同じように動く

## やらないこと

- 死亡・クリアの画面演出（Phase 3。ページは `effect` を受け取るだけ）
- 配信ログ（Phase 3）
- 設定やセリフの変更を起動中に読み直す機能

## 変更してよいファイル

- `src/stream_buddy/app.py`（新規）
- `src/stream_buddy/__main__.py`、`src/stream_buddy/server.py`、`src/stream_buddy/demo.py`
- `src/stream_buddy/audio.py`・`keywords.py`・`hotkey.py`（組み立てに必要な小さな変更のみ。変えたら理由を報告する）
- `tests/` 配下（このタスクに関係するもの）
- `README.md`（「特長」のみ）
- `docs/architecture.md`、`docs/status.md`
- `tasks/T-12-assembly.md`（このファイル。コミットに含める）

`src/stream_buddy/state/` と `lines.py` は変更しない。必要だと思ったら報告する。

## 完了条件

- [ ] 上記のテストがすべてあり、`uv run pytest` が通る
- [ ] `uv run ruff check .` / `uv run ruff format --check .` / `uv run mypy src` が通る
- [ ] `uv run stream-buddy --demo` で、OBS にメンダコが出て、テンション・セリフが状態機械どおりに動く
- [ ] `git status` に「変更してよいファイル」以外の変更がない
- [ ] `feat/assembly` ブランチでコミットした（push はしない）
- [ ] CLAUDE.md の形式で報告した
