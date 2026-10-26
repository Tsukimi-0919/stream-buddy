# アーキテクチャ

> これは「目指す姿」。今どこまでできているかは [status.md](status.md) を参照。

## 全体像

```
配信者の PC（外部への通信なし）
┌───────────────────────────────────────────────────────┐
│ マイク ──▶ audio ──▶ detect ──┐                          │
│                               ├─▶ state ──▶ server ──▶ OBS ブラウザソース │
│ ホットキー ──▶ hotkey ─────────┘     │          ▲         （overlay ページ）│
│                                     ▼          │                         │
│                                    log      config                       │
└───────────────────────────────────────────────────────┘
```

Python バックエンドがすべての判断を行い、OBS のページは「言われたとおりに表示する」だけにする。
両者をつなぐのは PC 内に閉じた WebSocket 1本で、ここが守るべき境界になる。

## モジュールと責務

予定するディレクトリ構成（`src/stream_buddy/` 配下）。

| モジュール | 責務 | 外に出すもの | 関連要件 |
| --- | --- | --- | --- |
| `config` | TOML の読み込みと検証。既定値の管理 | 設定オブジェクト | FR-11 |
| `audio` | マイクから音声を取り出す。保存しない | 音声フレーム（メモリ上） | FR-01 |
| `detect` | 発話の開始・終了、キーワードの検知 | 発話イベント、キーワードイベント | FR-02, FR-07 |
| `hotkey` | `RegisterHotKey` で決めたキーだけを受け取る | ホットキーイベント | FR-08, SR-05 |
| `state` | テンション管理、沈黙タイマー、セリフ選択 | 画面への指示 | FR-04〜FR-06 |
| `server` | ページの配信、WebSocket、認証 | `ws-protocol.md` のメッセージ | FR-03, SR-01〜SR-03 |
| `token_store` | 認証用トークンの作成・保存・読み込み（`%LOCALAPPDATA%\stream-buddy\token`） | トークン | SR-02 |
| `log` | 配信ログの Markdown 出力 | Markdown ファイル | FR-10, SR-06 |
| `overlay/`（HTML/CSS/JS） | メンダコ表示、吹き出し、演出 | なし（表示のみ） | FR-03, FR-09, SR-04 |

### `state` の中身

状態遷移の仕様は [state-machine.md](state-machine.md)。どのファイルも音声・ネットワーク・実時間を扱わず、時刻はミリ秒の引数で受け取る。

| ファイル | 中身 |
| --- | --- |
| `state/events.py` | 入力（`SpeechStarted`・`SpeechEnded`・`Keyword`・`Hotkey`・`Tick`）と出力（`Mouth`・`TensionChanged`・`Say`・`Effect`・`TensionPeak`）の型 |
| `state/constants.py` | state-machine.md の数値（窓、しきい値、待ち時間、吹き出しの最短間隔など） |
| `state/tension.py` | テンションの状態機械（ST-01〜ST-04） |
| `state/silence.py` | 沈黙ハンター（ST-11〜ST-15） |
| `state/event_fsm.py` | イベントの状態機械（ST-21〜ST-25） |
| `state/arbiter.py` | 出口：`Say` の優先順位と最短間隔 |
| `state/brain.py` | 4 つをまとめる `Brain`。入力を各状態機械に配り、出力を出口に通して返す。状態機械どうしをつなぐのはここだけ |

## 依存の向き

- `state` は入力（`detect`・`hotkey`）からイベントを受け取り、`server` と `log` に指示を出す
- `state` は音声やネットワークを直接扱わない（テストしやすくするため）
- `overlay` はバックエンドに指示を送らない。接続時の `hello` 以外は受信専用

## 起動の流れ（予定）

1. `config` を読み込み、検証する
2. 保存済みのトークンを読み込む。初回、形が違うとき、`--reset-token` のときは作り直して保存する（ADR 0002）
3. `server` が `127.0.0.1` で待ち受けを始める
4. OBS 用の URL（トークン入り）をコンソールに表示する
5. `audio`・`detect`・`hotkey` を開始する

## 技術選定（決定済み）

- Python（バージョンは `pyproject.toml` で固定）、uv、TOML
- Web サーバー：FastAPI ＋ uvicorn（Phase 1 で確定。変更する場合は ADR を書く）
- exe 化：PyInstaller

## 未決（ADR で決める）

- 音声認識エンジン（Vosk / faster-whisper）
- 発話検知の方式（音量しきい値 / VAD）
