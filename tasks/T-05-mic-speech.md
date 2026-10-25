# タスク：マイク入力と発話検知（声で口パク）

- ID：T-05
- Phase：1
- 関連要件：FR-01（マイク入力）、FR-02（発話検知）、NFR-01（軽さ）、NFR-02（反応速度）、NFR-05（保守性）、プライバシー方針
- ブランチ名：`feat/mic-speech`

## 目的

マイクの音量から「話している／話していない」を判定し、`speech` メッセージでページのメンダコを口パクさせる。
音声を扱う最初のタスクなので、**音声を保存しない・外に送らない・必要以上に持たない**ことを作りとテストで守る。

## 読む設計書

- `CLAUDE.md`
- `docs/requirements.md`（FR-01、FR-02、NFR-01、NFR-02、プライバシー）
- `docs/architecture.md`（`audio`・`detect` の責務と依存の向き）
- `src/stream_buddy/config.py`、`src/stream_buddy/server.py`、`src/stream_buddy/__main__.py`

## 追加してよい依存

- 実行時：`sounddevice`（マイク入力。Windows 用の wheel に PortAudio が同梱されている）、`numpy`
- これ以外は追加しない

## 仕様

### `audio` モジュール（`src/stream_buddy/audio.py`）

- `sounddevice.InputStream` で、モノラル・16 kHz・1 ブロック約 30 ms（480 サンプル）で入力する
- マイクの選び方：
  - 設定の `audio.device` が空なら OS の既定の入力デバイス
  - 空でなければ、入力デバイスの名前に**その文字列を含むもの**を選ぶ。見つからなければ、入力デバイス名の一覧を添えて日本語のエラーで終了する（終了コード 2）
- コールバックでは、ブロックごとに**音量（dBFS）だけを計算して**次の処理に渡す
  - 無音で計算できない場合は -100.0 とする
  - **音声のサンプル自体はコールバックの外に持ち出さない**。リストやキューにためない
- 音声をファイルに書き出す処理、音声ファイル用のライブラリ（`wave`、`soundfile` など）の import は**禁止**
- `sounddevice` を直接呼ぶ部分は小さく分け、テストでは偽物に差し替えられるようにする（CI には本物のマイクがないため）

### `detect` モジュール（`src/stream_buddy/detect.py`）

- 音量の列を受け取り、「話し始め」「話し終わり」の変化だけを返す、**音声もネットワークも扱わない**クラスにする
- 判定（ヒステリシス）：
  - しきい値（設定の `audio.speech_threshold_db`）を超えるブロックが **2 回続いたら**話し始め
  - しきい値以下のブロックが **300 ms 分続いたら**話し終わり（語尾や息継ぎで口パクが途切れないように）
  - 状態が変わったときだけ結果を返す（同じ状態を何度も通知しない）
- 時間はブロック数で数え、実時間（`time` モジュール）に依存しない（テストしやすくするため）

### 組み立て

- 音声のコールバック（別スレッド）から、`asyncio` のループへ `call_soon_threadsafe` で音量を渡す
- `detect` が変化を返したら、`speech` メッセージを `broadcast` する
- `--demo` のときはマイクを開かない
- `--list-devices` オプションを追加する：入力デバイスの番号と名前を表示して終了する（マイクの選び方を設定するときの手助け）
- 終了時（Ctrl+C）にストリームを確実に閉じる

## やること

1. `feat/mic-speech` ブランチを作る
2. 依存を追加する
3. `audio.py`、`detect.py` を作り、`__main__.py`（必要なら `server.py`）で組み立てる
4. テストを書く（本物のマイクは使わない）
   - `detect`：無音のまま／短いノイズ1ブロックだけ（話し始めにならない）／話し始め／短い息継ぎ（話し終わりにならない）／300 ms の無音で話し終わり／同じ状態を繰り返し通知しない
   - 音量の計算：無音が -100.0、フルスケールの正弦波がおよそ -3 dBFS
   - マイクの選び方：空なら既定、名前の一部で選べる、見つからなければエラーで一覧が出る（偽のデバイス一覧で確認）
   - 偽の入力ストリームから音量を流し込むと、`speech: true` → `speech: false` が `broadcast` される
   - `audio.py` と `detect.py` に、`wave`・`soundfile`・`open(`・`write` を使う処理がない（文字列で検査）
5. `config.example.toml` の `[audio]` のコメントに、`--list-devices` で名前を調べられることを書き足す
6. `README.md` の「プライバシー」が実装と合っているか確認する（合っていれば変更しない）
7. 手動確認の手順を報告に書く（`--list-devices`、実際に話してメンダコが口パクすること、しきい値の調整方法）
8. `docs/status.md` を更新する

## やらないこと

- 音声認識（言葉の聞き取り）。これは T-06 で比較してから決める
- テンションの計算、沈黙ハンター（Phase 2）
- VAD（声かどうかの判定）ライブラリの導入。今回は音量のしきい値だけで判定する
- サーバーの守り（Host・トークン・Origin・CSP）の変更

## 変更してよいファイル

- `pyproject.toml`、`uv.lock`（上記の依存の追加のみ）
- `src/stream_buddy/audio.py`、`src/stream_buddy/detect.py`（新規）
- `src/stream_buddy/__main__.py`、`src/stream_buddy/server.py`（組み立てに必要な範囲のみ）
- `tests/test_audio.py`、`tests/test_detect.py`（新規）、既存のテスト（組み立ての変更で必要な場合のみ）
- `config.example.toml`、`README.md`（上記の範囲のみ）
- `docs/status.md`
- `tasks/T-05-mic-speech.md`（このファイル。コミットに含める）

## 完了条件

- [ ] 上記のテストがすべてあり、`uv run pytest` が通る
- [ ] `uv run ruff check .` / `uv run ruff format --check .` / `uv run mypy src` が通る
- [ ] `uv sync --locked` が通る
- [ ] CI（Windows）で、本物のマイクがなくてもテストが通る作りになっている
- [ ] `uv run stream-buddy --list-devices` で入力デバイスが表示される
- [ ] `git status` に「変更してよいファイル」以外の変更がない
- [ ] `feat/mic-speech` ブランチでコミットした（push はしない）
- [ ] CLAUDE.md の形式で報告した
