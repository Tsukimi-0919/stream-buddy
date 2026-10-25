# 実装状況

> これは「今の姿」。目指す姿は [architecture.md](architecture.md) を参照。
> AI エージェントはタスク完了のたびにこのファイルを更新する。

## 現在のフェーズ

**Phase 1：実装中（T-03 完了）**

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
  - `/overlay?token=` は正しいトークンのときだけ仮のページ（`overlay/index.html`）を返し、それ以外は 404。`/docs` などは無効
  - `/static/` は `overlay/static/` フォルダがあるときだけ配信する（フォルダは T-04 で作る）
  - すべての HTTP 応答に CSP・`X-Content-Type-Options`・`Referrer-Policy`・`Cache-Control` を付ける
  - WebSocket は トークン・Origin・同時接続 2 本まで を確認してから受け入れる。受信は `hello` だけを受け付け、それ以外は破棄してエラーの種類だけをログに残す。4 KB 超で close 1009
  - `Hub.broadcast` でサーバー → ページのメッセージを送る
  - URL のトークンが出ないよう、uvicorn のアクセスログと info ログは止めている。FastAPI 組み込みの OpenTelemetry も止めている
  - `docs/ws-protocol.md` を確定版にした（JSON Schema ファイルは置かず、仕様と `protocol.py` の一致はテストで確認する）。`docs/threat-model.md` に DNS リバインディングを追記した

## まだないもの

- 機能モジュール（audio / detect / hotkey / state / log）
- 本番の OBS 用ページ（メンダコの表示、吹き出し、再接続）と `overlay/static/`
- メンダコの画像
- ログ出力先フォルダの存在確認・書き込み時のパス確認（ログのタスクで行う）

## 次にやること

- T-04（OBS 用のページ）
