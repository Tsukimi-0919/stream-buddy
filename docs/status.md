# 実装状況

> これは「今の姿」。目指す姿は [architecture.md](architecture.md) を参照。
> AI エージェントはタスク完了のたびにこのファイルを更新する。

## 現在のフェーズ

**Phase 1：実装中（T-05 完了）**

Phase 0（設計と守りの準備）は完了。

## できていること

- リポジトリの守り（pre-commit、Claude Code の禁止設定、CI、Dependabot）
- 設計書の初版（requirements / architecture / threat-model / ws-protocol）
- T-01：プロジェクトの土台（uv、`src/` レイアウト、Python 3.12 固定、ruff / mypy / pytest の設定）
  - `stream-buddy --version` でバージョンを表示できる
- T-02：設定ファイルの読み込みと検証（`src/stream_buddy/config.py`）
  - `load_config(path)` が TOML を読み、型と範囲を検証した変更不可の `Config` を返す。ファイルがなければ既定値
  - 知らないキー・範囲外の値・F1〜F12 以外のホットキー・death と clear の重複・`log.enabled = true` で `output_dir` が空／相対パス・壊れた TOML は、日本語メッセージの `ConfigError` になる
  - host は設定に含めない（SR-01）。`log.output_dir` はエラーメッセージに値を出さない
  - 設定例は `config.example.toml`
- T-03：ローカルサーバー（`src/stream_buddy/server.py`、`src/stream_buddy/protocol.py`）
  - 実行時の依存：pydantic、fastapi、uvicorn（`[standard]` なし）、websockets。開発用に httpx
  - `stream-buddy [--config <path>]` で起動。省略時はカレントフォルダの `config.toml`（なければ既定値）。設定エラーは終了コード 2
  - 起動時にトークン入りの OBS 用 URL をコンソールに1回だけ表示し、配信画面に映さないよう注意を出す
  - `127.0.0.1` 固定で待ち受け（定数 `HOST`）。`Host` ヘッダーが `127.0.0.1:<port>` 以外なら拒否（HTTP は 400、WebSocket は accept せずに閉じる）
  - `/overlay?token=` は正しいトークンのときだけページ（`overlay/index.html`）を返し、それ以外は 404。`/docs` などは無効
  - `/static/` は `overlay/static/` フォルダがあるときだけ配信する
  - すべての HTTP 応答に CSP・`X-Content-Type-Options`・`Referrer-Policy`・`Cache-Control` を付ける
  - WebSocket は トークン・Origin・同時接続 2 本まで を確認してから受け入れる。受信は `hello` だけを受け付け、それ以外は破棄してエラーの種類だけをログに残す。4 KB 超で close 1009
  - `Hub.broadcast` でサーバー → ページのメッセージを送る
  - URL のトークンが出ないよう、uvicorn のアクセスログと info ログは止めている。FastAPI 組み込みの OpenTelemetry も止めている
  - `docs/ws-protocol.md` を確定版にした（JSON Schema ファイルは置かず、仕様と `protocol.py` の一致はテストで確認する）。`docs/threat-model.md` に DNS リバインディングを追記した

- T-04：OBS 用のページ（`overlay/index.html`、`overlay/static/style.css`、`overlay/static/app.js`）
  - 仮のメンダコをオリジナルの SVG で描画（丸い体、ひれ、目、閉じた口と開いた口）
  - WebSocket で接続し `hello` を送る。切れたら 1 秒から倍々、上限 10 秒で再接続し、つながったら 1 秒に戻す
  - 受信メッセージは形を厳密に確認し、合わないものは無視。`speech`（口パク）、`tension`（calm / normal / high のアニメーション）、`say`（吹き出しを 5 秒表示）、`display`（透過 / 緑）を表示する。`effect` は受け取るだけ
  - 文字は `textContent` のみ。インラインのスクリプト・スタイル・`console` は使わない（テストで検査）
  - サーバーは `hello` を受け取ると、そのページにだけ設定の `display.background` を送る
  - `stream-buddy --demo` で、決まった流れ（`src/stream_buddy/demo.py`）を 2.5 秒間隔で繰り返し送る
  - Windows のレジストリの設定に左右されないよう、`.js` と `.css` の Content-Type を明示した
  - トークンを保存して使い回すようにした（ADR 0002、`src/stream_buddy/token_store.py`）
    - 初回に作って `%LOCALAPPDATA%\stream-buddy\token` に保存し、2回目以降は読み込む。形が違えば作り直す。書き込みは一時ファイル経由で置き換え
    - `--reset-token` で作り直し、OBS の URL の設定し直しを案内する。`LOCALAPPDATA` がなければ終了コード 2
    - stream-buddy を再起動しても URL が変わらず、ページは自動で再接続する
    - テストは `tests/conftest.py` で `LOCALAPPDATA` を一時フォルダに差し替え、実際の場所には書かない
- T-05：マイク入力と発話検知（`src/stream_buddy/audio.py`、`src/stream_buddy/detect.py`）
  - 実行時の依存に sounddevice、numpy を追加
  - モノラル・16 kHz・480 サンプル（約 30 ms）のブロックで入力し、コールバックの中で音量（dBFS、無音は -100.0）だけを計算する。サンプルは持ち出さない・ためない・ファイルに書かない
  - マイクは設定の `audio.device` が空なら OS の既定、空でなければ名前にその文字列を含む最初の入力デバイス。見つからなければ一覧を添えて終了コード 2
  - 発話検知はしきい値（`audio.speech_threshold_db`）を超えるブロックが 2 回続いたら話し始め、しきい値以下が 300 ms（10 ブロック）続いたら話し終わり。変化したときだけ `speech` を送る
  - 音声のスレッドからは `call_soon_threadsafe` で音量だけをループに渡し、1 本のタスクが順番どおりに `broadcast` する
  - `--list-devices` で入力デバイスの番号・名前・ホスト API を表示する。`--demo` のときはマイクを開かない。終了時（Ctrl+C を含む）にストリームを閉じる
  - テストでは sounddevice の代わりに偽のバックエンドを使う（`tests/conftest.py`）。本物のマイクがない CI でも通る

## まだないもの

- 機能モジュール（hotkey / state / log）
- 音声認識（T-06 で比較してから決める）
- CPU 使用率の計測（NFR-01）
- 死亡・クリアの演出（Phase 3）
- メンダコの本番の画像（今は仮の SVG）
- ログ出力先フォルダの存在確認・書き込み時のパス確認（ログのタスクで行う）

## 次にやること

- T-06（音声認識の比較）
