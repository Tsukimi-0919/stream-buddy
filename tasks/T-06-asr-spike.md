# タスク：音声認識エンジンの比較（スパイク）

- ID：T-06
- Phase：1
- 関連要件：FR-07（キーワード検知）、NFR-01（軽さ）、NFR-02（反応速度）、NFR-06（オフライン動作）、SR-07（モデルの改ざん）、プライバシー方針
- ブランチ名：`spike/asr-compare`

## 目的

キーワード検知（「死んだ」「勝った」など）に使う音声認識エンジンを、**Vosk** と **faster-whisper** から選ぶ。
実際の PC とマイクで、同じ音声を両方にかけて比べ、結果を ADR にする。
このタスクは**比較用の道具を作るところまで**。実際に話して測るのは人間が行う。

## 読む設計書

- `CLAUDE.md`
- `docs/requirements.md`（FR-07、NFR-01、NFR-02、NFR-06、SR-07、プライバシー）
- `src/stream_buddy/audio.py`、`src/stream_buddy/config.py`

## 比較用の依存（本体には入れない）

- `pyproject.toml` の `[dependency-groups]` に **`spike-asr` グループ**を作り、そこに `vosk` と `faster-whisper` を入れる
  - `uv add --group spike-asr vosk faster-whisper`
  - 本体の `dependencies` と `dev` グループには入れない（CI や exe に入らないように）
- 比較の結果、採用したエンジンを本体に入れるのは別のタスクで行う

## 外部への通信について（このタスクに限り許可）

- **faster-whisper**：初回実行時にモデルを Hugging Face から自動で取得してよい。取得先は `models/`（`.gitignore` 済み）にする
- **Vosk**：モデルはスクリプトから取得しない。人間が公式サイトから `vosk-model-small-ja-0.22` を手動で取得し `models/` に展開する。スクリプトはその場所を読む
- どちらのモデルも、比較の最後にフォルダの合計サイズと、主要なファイルの SHA-256 を表示する（ADR に記録して SR-07 の材料にするため）

## 比較用スクリプト（`spikes/asr_compare.py`）

### 音声の扱い（プライバシー方針を守る）

- マイクの選び方と入力形式は `audio.py` と同じ（モノラル・16 kHz、設定の `audio.device`）
- 1回の発話を**最大 3 秒だけメモリに持ち**、**同じ音声を両方のエンジンにかけて**から、すぐに捨てる
- 音声をファイルに保存しない。`wave`・`soundfile` などは使わない

### 測り方

- 画面に読み上げる言葉を1つずつ表示し、人間がそれを読む。録り終わりは音量で判定してよい（`detect.py` を流用してよい）
- 読み上げる言葉（各 3 回）
  - **キーワード**：「死んだ」「やられた」「勝った」「クリア」
  - **キーワードではない言葉**（誤検知を測る）：「しんどい」「かったるい」「クリーム」「今日はいい天気」
- エンジンごとの設定
  - Vosk：キーワードだけを候補にする文法（grammar）を指定し、`[unk]` も許す
  - faster-whisper：`tiny` と `base` の2種類、`device="cpu"`、`compute_type="int8"`、`language="ja"`。書き起こした文にキーワードが含まれるかで判定する
- 1回ごとに記録するもの
  - 判定結果（どのキーワードとして検知したか／検知なし）と、正解かどうか
  - 処理時間（音声を渡してから結果が出るまで、ミリ秒）
- 全体で記録するもの
  - エンジンごとの正解率、誤検知の数、処理時間の平均と最大
  - 処理中の CPU 時間の目安（`time.process_time` の差）
  - モデルの読み込み時間、モデルフォルダのサイズ
- 最後に、上記を**Markdown の表**で標準出力に出す。発話の書き起こし全文は表示してよいが、ファイルには保存しない

### 使い方

- `uv run --group spike-asr python spikes/asr_compare.py` で動く
- `--engines vosk,whisper-tiny,whisper-base` のように、試すエンジンを選べる
- `--rounds 3` で読み上げの回数を変えられる

## やること

1. `spike/asr-compare` ブランチを作る
2. `spike-asr` グループに依存を追加する
3. `spikes/asr_compare.py` と `spikes/README.md`（目的、Vosk モデルの手動取得手順、実行方法、注意事項）を作る
4. 動作確認は、**本物のマイクを開かずに**できる範囲で行う
   - マイクの代わりに、コード内で作った無音とノイズの配列を渡して、両エンジンがエラーなく動くこと
   - faster-whisper のモデル取得と読み込みができること
   - Vosk のモデルがないときに、手動取得の手順を案内して終了すること
5. `docs/adr/0003-asr-engine.md` を**ひな形だけ**作る（状態は「提案中」、比較の観点と表の枠。結果の数字は人間の測定後に書く）
6. `docs/status.md` を更新する

## やらないこと

- 本体（`src/`）の変更。キーワード検知の実装は、エンジンが決まってから別のタスクで行う
- 本物のマイクを開いての測定（人間が行う）
- 音声の保存、録音した音声を使った比較
- テストの追加（スパイクのため不要。ただし既存のテストと品質チェックは通すこと）

## 変更してよいファイル

- `pyproject.toml`、`uv.lock`（`spike-asr` グループの追加のみ）
- `spikes/asr_compare.py`、`spikes/README.md`（新規）
- `docs/adr/0003-asr-engine.md`（新規）
- `docs/status.md`
- `tasks/T-06-asr-spike.md`（このファイル。コミットに含める）

## 完了条件

- [ ] `uv sync --locked`（スパイクのグループなし）が通り、本体の依存が増えていない
- [ ] `uv run ruff check .` / `uv run ruff format --check .` / `uv run mypy src` / `uv run pytest` が通る
- [ ] 無音とノイズの配列で、選んだエンジンがエラーなく動く
- [ ] `spikes/README.md` の手順で、人間が測定を始められる
- [ ] `git status` に「変更してよいファイル」以外の変更がない
- [ ] `spike/asr-compare` ブランチでコミットした（push はしない）
- [ ] CLAUDE.md の形式で報告した
