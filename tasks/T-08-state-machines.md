# タスク：状態機械の実装（テンション・沈黙ハンター・イベント・出口）

- ID：T-08
- Phase：2
- 関連要件：FR-04、FR-05、FR-06（出し方の整理のみ）、FR-07・FR-08・FR-09（イベントの状態のみ）、NFR-05
- ブランチ名：`feat/state-machines`

## 目的

`docs/state-machine.md` の4つの状態機械と出口（Arbiter）を、**音声・ネットワーク・実時間に依存しない純粋なコード**として実装する。
遷移の ID（`ST-xx`）ごとにテストを書き、**Phase 2 のゲート「状態遷移図どおりに動くことをテストで確認」を満たす**。

## 読む設計書

- `CLAUDE.md`
- `docs/state-machine.md`（**このタスクの仕様そのもの**。数値と遷移はすべてここに従う）
- `docs/architecture.md`（`state` の責務と依存の向き）
- `src/stream_buddy/detect.py`（純粋なクラスの書き方の参考）

## 追加してよい依存

なし。標準ライブラリだけで書く。

## 仕様

### 置き場所

`src/stream_buddy/state/` パッケージを作る。

| ファイル | 中身 |
| --- | --- |
| `events.py` | 入力（`SpeechStarted`・`SpeechEnded`・`Keyword`・`Hotkey`・`Tick`）と出力（`Mouth`・`TensionChanged`・`Say`・`Effect`・`TensionPeak`）の型。`frozen=True` の dataclass |
| `tension.py` | テンションの状態機械（ST-01〜ST-04） |
| `silence.py` | 沈黙ハンター（ST-11〜ST-15） |
| `event_fsm.py` | イベントの状態機械（ST-21〜ST-25） |
| `arbiter.py` | 出口：`Say` の優先順位と最短間隔 |
| `brain.py` | 4つをまとめる `Brain`：入力を各状態機械に配り、出力を出口に通して返す |
| `constants.py` | `state-machine.md` の数値をすべてここに定数として置く（窓 30 秒、しきい値、5 秒、+30 / −30、10 秒、20 秒、3 回、演出 3 秒、待ち時間 10 秒、吹き出しの最短間隔 5 秒、tick 100 ms） |

### 共通の約束

- 各状態機械は、`step(input, now_ms) -> list[出力]` を持つクラスにする。**時刻は必ず引数で受け取り**、`time` モジュールを import しない
- 状態機械どうしは直接呼び合わない。つなぐのは `Brain` だけ
- 沈黙ハンターの「演出中は数えない」は、`Brain` がイベントの状態機械の状態を見て伝える
- 沈黙の秒数（`silence.seconds`）は設定から渡す。それ以外の数値は `constants.py` の定数
- 乱数は使わない（セリフ選びは T-09）。出口は `Say(situation)` の「出すか・出さないか」だけを決める

### テンション（ST-01〜ST-04）

- 盛り上がり度 = 直近 30 秒のうち話していた時間の割合 × 100 ＋ イベントの補正
  - 話していた時間は `SpeechStarted` / `SpeechEnded` の時刻から求める。話している最中は「今」までを数える
  - クリアで +30、死亡で −30。補正は 10 秒かけて**直線的に 0 に戻る**。結果は 0〜100 に収める
- 判定は `Tick` のたびに行う
- 状態を変えたら、そこから 5 秒は変えない（起動直後の 5 秒も変えない）
- Calm から High へ、High から Calm へは一度に飛ばない
- High に入ったら `TensionChanged(high)`・`TensionPeak`・`Say(high)` を出す

### 沈黙ハンター（ST-11〜ST-15）

- 起動直後は Listening。最初の `SpeechEnded` までは数えない
- Waiting で、最後の `SpeechEnded` から待ち時間を超えたら `Say(silence)`。回数 +1、待ち時間を 2 倍にし、そこから数え直す
- 3 回話しかけたら GaveUp。`SpeechStarted` で Listening に戻る
- 演出中（イベントが Effecting）の時間は、沈黙の時間に**数えない**

### イベント（ST-21〜ST-25）

- `Keyword(k)` と `Hotkey(k)` の `k` は `death` / `clear`
- Ready で入力 → Effecting。`Effect(k)`・`Say(k)` を出し、テンションに補正（クリア +30 / 死亡 −30）を伝える
- 演出開始から 3 秒で Cooldown、10 秒で Ready
- Cooldown 中：`Hotkey` は受け付けて Effecting へ。`Keyword` は無視
- Effecting 中：すべて無視

### 出口（Arbiter）

- `Say(death)` / `Say(clear)`：常に出す
- `Say(high)` / `Say(silence)`：前に出した `Say` から 5 秒以上あいていれば出す。あいていなければ**捨てる**（後で出し直さない）
- 同じ時刻に複数の `Say` が来たら、優先度の高いものだけを出す
- `Mouth`・`TensionChanged`・`Effect`・`TensionPeak` は間引かずに通す
- `Mouth` は `SpeechStarted` / `SpeechEnded` から `Brain` が作る

## テスト

`tests/state/` に置く。**テスト関数の名前に遷移の ID を入れる**（例：`test_st01_calm_to_normal`）。

最低限、次を確かめる。

- ST-01〜ST-04、ST-11〜ST-15、ST-21〜ST-25 のそれぞれの遷移と、そのときの出力
- 各遷移の**境界**（しきい値ちょうど、5 秒ちょうど、20 秒ちょうど など）で、仕様どおりに変わる／変わらない
- テンション：5 秒以内は変わらない、Calm → High に一度に飛ばない、クリアの補正で Normal → High になる、死亡の補正で下がる、補正が 10 秒で消える
- 沈黙ハンター：起動直後は数えない、20 → 40 → 80 秒で話しかけて止まる、話すと最初に戻る、演出中の時間は数えない
- イベント：キーワードの連続が無視される、Cooldown 中のホットキーで演出が出る、Effecting 中は何も受け付けない
- 出口：5 秒以内の `Say(silence)` が捨てられる、`Say(clear)` は間隔に関係なく出る、同時の `Say` は優先度で1つになる
- `Brain` を通した**シナリオテスト**を2つ以上（例：「話して盛り上がる → クリア → High → 黙る → 沈黙ハンター」）
- `src/stream_buddy/state/` のどのファイルも `time`・`random`・`asyncio`・`sounddevice`・`fastapi` を import していない（文字列で検査）
- 各遷移 ID がテスト名に1回以上出てくることを確かめるテスト（`docs/state-machine.md` から `ST-xx` を抜き出して照合する）

## やること

1. `feat/state-machines` ブランチを作る
2. 上記のパッケージとテストを作る
3. 実装中に `state-machine.md` と食い違う点や、仕様が足りない点を見つけたら、**実装で勝手に決めずに報告する**（小さなものは「こう解釈した」と報告に書く）
4. `docs/architecture.md` のモジュール表に `state` の中身を追記する
5. `docs/status.md` を更新する

## やらないこと

- セリフの選択とセリフファイル（T-09）
- キーワード検知、ホットキー（T-10、T-11）
- サーバーや音声との組み立て、`--demo` の変更（T-12）
- 配信ログ（Phase 3）
- `docs/state-machine.md` の変更（食い違いは報告のみ）

## 変更してよいファイル

- `src/stream_buddy/state/` 配下（新規）
- `tests/state/` 配下（新規）
- `docs/architecture.md`、`docs/status.md`
- `tasks/T-08-state-machines.md`（このファイル。コミットに含める）

## 完了条件

- [ ] すべての `ST-xx` にテストがあり、`uv run pytest` が通る
- [ ] `uv run ruff check .` / `uv run ruff format --check .` / `uv run mypy src` が通る
- [ ] `src/stream_buddy/state/` が禁止した import を含まない
- [ ] `git status` に「変更してよいファイル」以外の変更がない
- [ ] `feat/state-machines` ブランチでコミットした（push はしない）
- [ ] CLAUDE.md の形式で報告した。仕様の解釈や食い違いがあれば、それも書いた
