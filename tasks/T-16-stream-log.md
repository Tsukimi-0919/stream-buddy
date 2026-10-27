# タスク：配信ログ（Markdown・Obsidian 対応）

- ID：T-16
- Phase：3
- 関連要件：FR-10（配信ログ）、FR-11（設定）、SR-06（ログの出力先）、プライバシー方針
- ブランチ名：`feat/stream-log`

## 目的

配信中の「テンションが High になった」「死亡」「クリア」の時刻を、Markdown のファイルに残す。
アーカイブ動画の見どころ探しに使え、Obsidian の Vault にそのまま置けるようにする。

## 読む設計書

- `CLAUDE.md`
- `docs/requirements.md`（FR-10、SR-06、プライバシー）、`docs/threat-model.md`（SR-06）
- `docs/state-machine.md`（出力の `TensionPeak`・`Effect`）
- `src/stream_buddy/config.py`（`[log]`）、`src/stream_buddy/app.py`、`src/stream_buddy/__main__.py`

## 追加してよい依存

なし。

## 設定の見直し

Vosk はキーワードとおとりの言葉だけを聞き取る作り（ADR 0003）のため、**話した文章全体はどこにも存在しない**。
そこで、`[log]` の `include_speech_text` を廃止し、次に置き換える。

```toml
[log]
enabled = false
output_dir = ""          # enabled = true のときは必須。絶対パスのみ。フォルダはあらかじめ作っておく
include_keyword = false  # true のとき、キーワードで起きた死亡・クリアに、検知した言葉（例：死んだ）を添える
```

- `include_speech_text` が設定ファイルに書かれていたら、知らないキーとして**エラー**にする（今までどおり）。エラーメッセージで `include_keyword` に変わったことを案内する
- `docs/requirements.md` のプライバシーと FR-10、`config.example.toml` を合わせて直す

## 仕様

### いつ・どこに書くか

- `log.enabled = true` のとき、起動ごとに**新しいファイルを1つ**作る
  - ファイル名：`stream-buddy-YYYY-MM-DD-HHMMSS.md`（起動した日時。ローカル時刻）
  - 置き場所：`log.output_dir` の**直下**
- 起動時の確認（失敗したら、ほかを始める前にエラーで起動しない）
  - `output_dir` が存在し、フォルダであること（**フォルダは作らない**）
  - 書き込めること
- できごとが起きるたびに、**その場で1行書き足して `flush` する**（途中で落ちても、そこまでの記録が残るように）
- 終了時（Ctrl+C を含む）に「まとめ」を書き足して閉じる。まとめが書けずに落ちても、それまでの行は残る

### 書き込み先の守り（SR-06）

- ファイル名は日時から**プログラムが作る**。設定や外からの文字列をファイル名に使わない
- 書き込む前に、`output_dir` と作るファイルのパスを `resolve()` で正規化し、ファイルが `output_dir` の**直下にある**ことを確かめる
- ファイルは**新規作成専用**（`open(..., "x")`）で開く。同じ名前のファイルがすでにあれば、末尾に `-2`、`-3` … を付けて作り直す（上書きしない）。10 回試してだめならエラー
- 文字コードは UTF-8（BOM なし）、改行は LF

### 書く内容

```markdown
---
date: 2026-10-27
start: "20:00:12"
tags: [stream-buddy]
---
# 配信ログ 2026-10-27 20:00

| 経過 | 時刻 | できごと |
| --- | --- | --- |
| 00:12:34 | 20:12:46 | テンション High |
| 00:15:02 | 20:15:14 | クリア |
| 00:31:40 | 20:31:52 | 死亡（死んだ） |

## まとめ

- 配信時間：1:02:15
- テンション High：3 回
- 死亡：5 回
- クリア：2 回
```

- **経過**は起動からの時間（`time.monotonic()` の差。時計の変更に影響されない）、**時刻**はローカルの壁時計
- 記録するできごと
  - `TensionPeak` → 「テンション High」
  - `Effect(death)` → 「死亡」、`Effect(clear)` → 「クリア」
  - `include_keyword = true` で、キーワードで起きた演出のときだけ、検知した言葉を `（死んだ）` のように添える。ホットキーのときは添えない
- 記録しないもの：音声、セリフの文字列、沈黙ハンター、口パク、トークン、ファイルのパス
- Markdown として壊れないよう、表に書く文字列から `|` と改行を取り除く（キーワードは設定で検証済みだが、念のため）

### キーワードの言葉を渡す

- 検知した言葉を記録に使うため、`keywords.py` から `Keyword(kind)` と一緒に**検知した言葉**（設定に書いたキーワードのうちどれか）を渡せるようにする
  - 状態機械（`state/`）は変更しない。`app.py` で、`Keyword` を `Brain` に入れたときの言葉を覚えておき、直後の `Effect` に対応させる
  - 渡すのは**設定に書いたキーワードそのもの**だけ。Vosk の認識結果の文字列は渡さない

### 時計の差し替え

- 壁時計と `monotonic` の両方を、テストで差し替えられるようにする

## テスト（`tests/test_stream_log.py` など）

- `enabled = false`：ファイルを作らない
- 起動時の確認：`output_dir` がない・ファイルである・書き込めないときにエラー。フォルダを作らない
- ファイル名：日時から作られる。同じ名前があれば `-2` を付け、既存のファイルの中身は変わらない
- 書き込み先：作ったファイルが `output_dir` の直下にある（`resolve()` の結果で確かめる）
- 内容：フロントマター、表の見出し、`TensionPeak`・死亡・クリアの行、経過と時刻の形（偽の時計で確かめる）、まとめの回数と配信時間
- `include_keyword`：`false` なら言葉を添えない、`true` ならキーワードの演出にだけ添え、ホットキーの演出には添えない
- その場で書き足す：できごとのたびに、ファイルを読むとその行がある（閉じる前でも）
- まとめを書く前に例外が起きても、それまでの行が残る
- 記録しないもの：ログにトークン・パス・セリフの文字列が含まれない
- `include_speech_text` が設定にあるとエラーになり、メッセージで `include_keyword` を案内する

## やること

1. `feat/stream-log` ブランチを **`origin/main` から**作る
2. 設定の見直し、`src/stream_buddy/stream_log.py`（新規）、`app.py`・`keywords.py`・`__main__.py` の変更
3. テストを書く
4. 設計書（requirements・threat-model・architecture）、`config.example.toml`、`README.md`（ログの使い方と、記録するもの・しないもの）を直す
5. `docs/status.md` を更新する
6. 手動確認の手順を報告に書く

## 手動確認（人が行う）

1. Obsidian の Vault の中などにフォルダを作り、`config.toml` に `[log] enabled = true`、`output_dir = "そのフォルダの絶対パス"` を書く
2. `uv run stream-buddy --demo` を1分ほど動かして止める
3. フォルダにファイルができ、High・死亡・クリアの行とまとめが入っている
4. Obsidian で開いて、表とフロントマターがきれいに表示される
5. `include_keyword = true` にして、実際に「死んだ」と言うと、`死亡（死んだ）` と記録される

## やらないこと

- ログの自動削除やファイルのまとめ
- 配信ソフトの録画時間との同期
- 音声や会話の文字起こしの保存（存在しないため）

## 変更してよいファイル

- `src/stream_buddy/stream_log.py`（新規）
- `src/stream_buddy/config.py`、`src/stream_buddy/app.py`、`src/stream_buddy/keywords.py`、`src/stream_buddy/__main__.py`
- `config.example.toml`、`README.md`（ログの説明のみ）
- `tests/` 配下（このタスクに関係するもの）
- `docs/requirements.md`、`docs/threat-model.md`、`docs/architecture.md`、`docs/status.md`
- `tasks/T-16-stream-log.md`（このファイル。コミットに含める）

`src/stream_buddy/state/` は変更しない。

## 完了条件

- [ ] 上記のテストがすべてあり、`uv run pytest` が通る
- [ ] `uv run ruff check .` / `uv run ruff format --check .` / `uv run mypy src` が通る
- [ ] `git status` に「変更してよいファイル」以外の変更がない
- [ ] `feat/stream-log` ブランチでコミットした（push はしない）
- [ ] CLAUDE.md の形式で報告した
