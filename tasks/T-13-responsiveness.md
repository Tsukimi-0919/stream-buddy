# タスク：反応の調整（吹き出しの間隔・盛り上げセリフ・キーワードの速さ）

- ID：T-13
- Phase：2（調整）
- 関連要件：FR-04、FR-06、FR-07、NFR-02
- ブランチ名：`feat/responsiveness`

## 目的

Phase 2 のゲートで「動くが、セリフの間隔とキーワードの反応が遅い」とわかった。次の3つで改善する。

1. 吹き出しの最短間隔を 5 秒 → **3 秒**にする
2. High が続いている間、**15 秒ごとに盛り上げセリフ**を言う
3. キーワードを、話し終わりを待たずに**途中の結果（部分結果）**で検知する

## 読む設計書

- `CLAUDE.md`
- `docs/state-machine.md`（テンション、出口、決定の記録、解釈の補足）
- `docs/adr/0003-asr-engine.md`（おとりの言葉と誤検知の記録）
- `src/stream_buddy/state/`、`src/stream_buddy/lines.py`、`src/stream_buddy/data/lines.toml`、`src/stream_buddy/keywords.py`

## 追加してよい依存

なし。

## 今回に限り変更を許可するもの

- `docs/state-machine.md`（下の仕様の反映）
- `src/stream_buddy/state/`（下の仕様の反映）
- `src/stream_buddy/data/lines.toml`（**下に書いた `cheer` のリストを、文言そのままで追加することだけ**。ほかのセリフは変えない）

## 仕様

### 1. 吹き出しの最短間隔

- `constants.py` の最短間隔を 3 秒にする
- `docs/state-machine.md` の該当箇所と「決定の記録」を更新する（「5 秒（暫定）」→「3 秒（2026-10-27 に変更）」）

### 2. 盛り上げセリフ（新しい遷移 ST-05）

- High の間、High に入った時刻（または前回の盛り上げセリフの時刻）から **15 秒**たつごとに `Say(cheer)` を出す
- High を出たら数えるのをやめ、次に High に入ったらそこから数え直す
- 判定は `Tick` のたびに行う
- 出口での優先度は `high` と同じ（2）。最短間隔に引っかかったら捨てる（今までの `Say` と同じ扱い）
- 15 秒は `constants.py` に定数として置く
- `docs/state-machine.md` のテンションの図と表に **ST-05** を追加する

| ID | いまの状態 | 条件 | 次の状態 | 出力 |
| --- | --- | --- | --- | --- |
| ST-05 | High | High に入ってから、または前回の `Say(cheer)` から 15 秒 | High（変わらない） | `Say(cheer)` |

- セリフ集に `[tension]` の `cheer` を追加する（必須のリストが 7 つになる）。文言は次のとおり：

```toml
cheer = [
  "まだまだいけるよ～！",
  "この勢い、止まらないね！",
  "ボク、ずっとワクワクしてる！",
  "いいねいいね～！ その調子！",
  "チャットも盛り上がってるかな？🔥",
]
```

- `lines.py` の場面の対応に `cheer` → `[tension] cheer` を加える
- 自分のセリフ集を使っている人のファイルに `cheer` がなければ、今までどおり**エラーで起動しない**（足りない場所をメッセージで示す）。`config.example.toml` か README のセリフ集の説明に、`cheer` が加わったことを書く

### 3. キーワードの部分結果での検知

- 認識用のスレッドで、Vosk の**部分結果（`PartialResult`）**も判定する
  - 判定のしかた（おとり・キーワード・2種類）は最終結果と同じ
  - **同じ判定（同じ種類）が 150 ms 以上続いたら**検知とする（途中の結果の揺れで「やっぱり」が一瞬「やったー」に見えても反応しないように）。150 ms は `keywords.py` の定数
  - 時刻は外から渡せるようにする（テストのため）
- **1つの発話につき1回まで**：部分結果で検知したら、その発話の最終結果が出るまで、同じ発話からはもう検知しない。最終結果で発話の区切りとする
- 部分結果で検知しなかった発話は、今までどおり最終結果で判定する
- 部分結果の文字列も、ファイル・ログ・コンソールに出さない

### 4. 反応の速さを見る

- `--test-keywords` の表示に、**話し終わり（`detect` の `SpeechEnded`）から検知までの時間**をミリ秒で添える（例：`clear (-120 ms)`）。話し終わる前に検知したときは負の値になる。認識した文字列は今までどおり出さない

## テスト

- 出口：3 秒の境界（2999 ms で捨てる、3000 ms で出す）
- ST-05：High に入って 15 秒で `Say(cheer)`、30 秒で2回目、High を出ると止まる、入り直すと数え直す、最短間隔に引っかかると捨てる。テスト名に `st05` を入れる（`ST-xx` の照合テストが通ること）
- セリフ集：`cheer` を含む7つのリストが必須、`cheer` がないとエラー、`cheer` のセリフが `say` として正しい
- 部分結果：
  - キーワードの部分結果が 150 ms 続くと検知、149 ms では検知しない
  - 「やったー」→「やっぱり」のように途中で判定が変わると、検知しない
  - おとりが含まれる部分結果では検知しない
  - 部分結果で検知した発話は、最終結果で2回目の検知をしない
  - 部分結果で検知しなかった発話は、最終結果で検知する
- `--test-keywords` の時間の表示（偽の時計で確かめる）

## やること

1. `feat/responsiveness` ブランチを作る（**`origin/main` から**）
2. 上の仕様を実装し、テストを書く
3. `docs/state-machine.md`、`docs/status.md` を更新する
4. 手動確認の手順を報告に書く

## 手動確認（人が行う）

- `--test-keywords` で「死んだ」「やったー」を各 5 回話し、検知までの時間を記録する
- 「やっぱり」を 10 回話して、`clear` が出ないことを確かめる（部分結果での誤検知の確認）
- 「わかった」「クリーム」も各 5 回話して、検知しないことを確かめる
- `uv run stream-buddy` で、High の間に盛り上げセリフが出ること、セリフの間隔が短くなったことを OBS で確かめる

## やらないこと

- テンションのしきい値や窓の長さの変更
- `high`・`silence`・`death`・`clear` のセリフの変更
- 演出（Phase 3）

## 変更してよいファイル

- `src/stream_buddy/state/` 配下、`src/stream_buddy/lines.py`、`src/stream_buddy/keywords.py`、`src/stream_buddy/__main__.py`（`--test-keywords` の表示のみ）
- `src/stream_buddy/data/lines.toml`（`cheer` の追加のみ）
- `config.example.toml`、`README.md`（セリフ集の説明のみ）
- `tests/` 配下（このタスクに関係するもの）
- `docs/state-machine.md`、`docs/status.md`
- `tasks/T-13-responsiveness.md`（このファイル。コミットに含める）

## 完了条件

- [ ] 上記のテストがすべてあり、`uv run pytest` が通る
- [ ] `uv run ruff check .` / `uv run ruff format --check .` / `uv run mypy src` が通る
- [ ] `lines.toml` の変更が `cheer` の追加だけである（`git diff` で確かめる）
- [ ] `git status` に「変更してよいファイル」以外の変更がない
- [ ] `feat/responsiveness` ブランチでコミットした（push はしない）
- [ ] CLAUDE.md の形式で報告した
